"""Attach user-specific execution and position fields to shared opportunity rows."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from app.infrastructure.persistence import arbitrage_execution_repository
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.utils.formatters import format_usd_compact


class OpportunityUserOverlayService:
    def enrich_execution_rows(
        self,
        *,
        user_id: int,
        channel: str,
        rows: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        account_rows = account_repository.list_active_accounts_with_address_by_user_id(user_id)
        account_lookup = self._build_account_lookup(account_rows)
        normalized_channel = str(channel or "").strip().lower()
        return [
            self._enrich_execution_row(
                channel=normalized_channel,
                row=row,
                account_lookup=account_lookup,
            )
            for row in rows
            if isinstance(row, dict)
        ]

    def enrich_display_rows(
        self,
        *,
        user_id: int,
        channel: str,
        rows: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        enriched_rows = self.enrich_execution_rows(user_id=user_id, channel=channel, rows=rows)
        account_ids = sorted(
            {
                int(item.get("left_account_id") or 0)
                for item in enriched_rows
            }
            | {
                int(item.get("right_account_id") or 0)
                for item in enriched_rows
            }
        )
        account_ids = [account_id for account_id in account_ids if account_id > 0]
        symbols = sorted(
            {
                str(item.get("left_symbol_raw") or "").strip()
                for item in enriched_rows
            }
            | {
                str(item.get("right_symbol_raw") or "").strip()
                for item in enriched_rows
            }
        )
        symbols = [symbol for symbol in symbols if symbol]
        position_rows = arbitrage_execution_repository.list_open_positions_for_accounts(
            user_id=user_id,
            account_ids=account_ids,
            symbols=symbols,
        )
        position_lookup = self._build_position_lookup(position_rows)

        result: List[Dict[str, Any]] = []
        for row in enriched_rows:
            item = dict(row)
            left_quantity = self._resolve_position_quantity(
                lookup=position_lookup,
                account_id=int(item.get("left_account_id") or 0),
                market_type=str(item.get("left_market_type") or ""),
                symbol=str(item.get("left_symbol_raw") or ""),
                position_side="long",
            )
            right_quantity = self._resolve_position_quantity(
                lookup=position_lookup,
                account_id=int(item.get("right_account_id") or 0),
                market_type=str(item.get("right_market_type") or ""),
                symbol=str(item.get("right_symbol_raw") or ""),
                position_side="short",
            )
            item["qty_long"] = self._format_quantity(left_quantity, str(item.get("symbol") or ""))
            item["qty_short"] = self._format_quantity(right_quantity, str(item.get("symbol") or ""))
            item["value_long"] = self._format_value(left_quantity, self._to_float(item.get("left_price_value")))
            item["value_short"] = self._format_value(right_quantity, self._to_float(item.get("right_price_value")))
            result.append(item)
        return result

    def _enrich_execution_row(
        self,
        *,
        channel: str,
        row: Dict[str, Any],
        account_lookup: Dict[Tuple[str, str], Dict[str, Any]],
    ) -> Dict[str, Any]:
        item = dict(row)
        left_market_type = str(item.get("left_market_type") or ("swap" if channel == "funding" else "")).strip().lower()
        right_market_type = str(item.get("right_market_type") or ("swap" if channel == "funding" else "")).strip().lower()
        left_exchange_code = str(item.get("left_exchange_code") or "").strip().lower()
        right_exchange_code = str(item.get("right_exchange_code") or "").strip().lower()
        left_account = account_lookup.get((left_exchange_code, left_market_type))
        right_account = account_lookup.get((right_exchange_code, right_market_type))
        left_price = self._to_float(item.get("left_price_value"))
        right_price = self._to_float(item.get("right_price_value"))
        left_available = self._account_available_amount(left_account)
        right_available = self._account_available_amount(right_account)
        executable_qty_left = self._estimate_quantity(left_available, left_price)
        executable_qty_right = self._estimate_quantity(right_available, right_price)
        has_required_accounts = left_account is not None and right_account is not None
        execution_ready = (
            has_required_accounts
            and bool(item.get("has_market_data"))
            and bool(item.get("is_market_data_fresh"))
            and bool(item.get("is_price_aligned", True))
            and executable_qty_left > 0
            and executable_qty_right > 0
        )

        item["left_account_id"] = int((left_account or {}).get("id") or 0)
        item["right_account_id"] = int((right_account or {}).get("id") or 0)
        item["left_market_type"] = left_market_type
        item["right_market_type"] = right_market_type
        item["has_required_accounts"] = has_required_accounts
        item["execution_ready"] = execution_ready
        item.setdefault("qty_long", self._format_quantity(0, str(item.get("symbol") or "")))
        item.setdefault("qty_short", self._format_quantity(0, str(item.get("symbol") or "")))
        item.setdefault("value_long", "$0")
        item.setdefault("value_short", "$0")
        return item

    def _build_account_lookup(self, rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
        lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for row in rows:
            if not bool(row.get("is_active", True)):
                continue
            if not self._is_account_execution_ready(row):
                continue
            market_code = str(row.get("market_type") or "").strip().lower()
            exchange_code = str(row.get("exchange_code") or "").strip().lower()
            if not market_code or not exchange_code:
                continue
            key = (exchange_code, market_code)
            existing = lookup.get(key)
            if existing is None or self._account_available_amount(row) > self._account_available_amount(existing):
                lookup[key] = row
        return lookup

    def _build_position_lookup(self, rows: List[Dict[str, Any]]) -> Dict[Tuple[int, str, str, str], float]:
        lookup: Dict[Tuple[int, str, str, str], float] = {}
        for row in rows:
            try:
                account_id = int(row.get("exchange_account_id") or 0)
            except (TypeError, ValueError):
                continue
            if account_id <= 0:
                continue
            key = (
                account_id,
                str(row.get("market_type") or "").strip().lower(),
                str(row.get("symbol") or "").strip(),
                str(row.get("position_side") or "net").strip().lower(),
            )
            lookup[key] = self._to_float(row.get("quantity"))
        return lookup

    def _resolve_position_quantity(
        self,
        *,
        lookup: Dict[Tuple[int, str, str, str], float],
        account_id: int,
        market_type: str,
        symbol: str,
        position_side: str,
    ) -> float:
        if account_id <= 0 or not market_type or not symbol:
            return 0.0
        exact_key = (account_id, market_type.strip().lower(), symbol.strip(), position_side.strip().lower())
        if exact_key in lookup:
            return max(lookup[exact_key], 0.0)
        net_key = (account_id, market_type.strip().lower(), symbol.strip(), "net")
        return max(lookup.get(net_key, 0.0), 0.0)

    def _is_account_execution_ready(self, row: Dict[str, Any]) -> bool:
        status = str(row.get("connection_test_status") or "").strip().lower()
        if status == "success":
            return True
        return row.get("current_available_synced_at") is not None

    def _account_available_amount(self, row: Dict[str, Any] | None) -> float:
        if row is None:
            return 0.0
        return self._to_float(row.get("current_available_amount"))

    def _estimate_quantity(self, available_amount: float, price: float) -> float:
        if available_amount <= 0 or price <= 0:
            return 0.0
        usable = min(available_amount, 1000.0)
        return usable / price

    def _format_quantity(self, quantity: float, base_asset: str) -> str:
        if quantity <= 0:
            return f"0.0000 {base_asset}".strip()
        if quantity >= 1000:
            return f"{quantity:,.0f} {base_asset}".strip()
        if quantity >= 1:
            return f"{quantity:,.2f} {base_asset}".strip()
        return f"{quantity:,.4f} {base_asset}".strip()

    def _format_value(self, quantity: float, price: float) -> str:
        if quantity <= 0 or price <= 0:
            return "$0"
        return format_usd_compact(quantity * price)

    def _to_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


opportunity_user_overlay_service = OpportunityUserOverlayService()

