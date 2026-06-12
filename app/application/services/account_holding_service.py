"""Resolve real per-symbol holdings for the current display page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Dict, List

from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.exchange_connection_service import exchange_connection_service
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.utils.formatters import format_usd_compact


@dataclass
class AccountHoldingSnapshot:
    account_id: int
    market_type: str
    synced_at: datetime
    spot_balances: Dict[str, float]
    swap_positions: Dict[str, float]


class AccountHoldingService:
    def __init__(self) -> None:
        self._cache: Dict[int, AccountHoldingSnapshot] = {}
        self._lock = RLock()
        self._ttl = timedelta(seconds=60)

    def enrich_opportunity_rows(
        self,
        *,
        user_id: int,
        channel: str,
        rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []

        account_rows = account_repository.list_accounts_with_address_by_user_id(user_id)
        account_map = {int(row["id"]): row for row in account_rows}
        enriched_rows: List[Dict[str, Any]] = []

        for row in rows:
            item = dict(row)
            left_market_type = "swap" if channel == "funding" else str(item.get("left_market_type") or "")
            right_market_type = "swap" if channel == "funding" else str(item.get("right_market_type") or "")

            left_quantity = self._resolve_row_leg_quantity(
                account_map=account_map,
                account_id=item.get("left_account_id"),
                market_type=left_market_type,
                symbol=str(item.get("left_symbol_raw") or ""),
                base_asset=str(item.get("symbol") or ""),
            )
            right_quantity = self._resolve_row_leg_quantity(
                account_map=account_map,
                account_id=item.get("right_account_id"),
                market_type=right_market_type,
                symbol=str(item.get("right_symbol_raw") or ""),
                base_asset=str(item.get("symbol") or ""),
            )

            left_price = self._parse_float(item.get("left_price_value"))
            right_price = self._parse_float(item.get("right_price_value"))

            item["qty_long"] = self._format_quantity(left_quantity, str(item.get("symbol") or ""))
            item["qty_short"] = self._format_quantity(right_quantity, str(item.get("symbol") or ""))
            item["value_long"] = self._format_value(left_quantity, left_price)
            item["value_short"] = self._format_value(right_quantity, right_price)
            enriched_rows.append(item)

        return enriched_rows

    def _resolve_row_leg_quantity(
        self,
        *,
        account_map: Dict[int, Dict[str, Any]],
        account_id: Any,
        market_type: str,
        symbol: str,
        base_asset: str,
    ) -> float:
        try:
            account_id_int = int(account_id or 0)
        except (TypeError, ValueError):
            return 0.0
        if account_id_int <= 0:
            return 0.0

        account_row = account_map.get(account_id_int)
        if account_row is None:
            return 0.0

        snapshot = self._get_snapshot(account_row)
        if market_type == "spot":
            return max(float(snapshot.spot_balances.get(base_asset.upper(), 0.0)), 0.0)

        normalized_symbol = symbol.strip()
        if normalized_symbol:
            return max(float(snapshot.swap_positions.get(normalized_symbol, 0.0)), 0.0)
        return 0.0

    def _get_snapshot(self, account_row: Dict[str, Any]) -> AccountHoldingSnapshot:
        account_id = int(account_row["id"])
        with self._lock:
            cached = self._cache.get(account_id)
            if cached is not None and datetime.now() - cached.synced_at <= self._ttl:
                return cached

        try:
            snapshot = self._fetch_snapshot(account_row)
        except Exception:
            snapshot = AccountHoldingSnapshot(
                account_id=account_id,
                market_type=str(account_row.get("market_type") or "").strip().lower(),
                synced_at=datetime.now(),
                spot_balances={},
                swap_positions={},
            )
        with self._lock:
            self._cache[account_id] = snapshot
        return snapshot

    def _fetch_snapshot(self, account_row: Dict[str, Any]) -> AccountHoldingSnapshot:
        market_type = str(account_row.get("market_type") or "").strip().lower()
        client = exchange_connection_service.build_exchange_client(
            ExchangeConnectionTestRequest(
                account_id=int(account_row["id"]),
                market_type=market_type,
                exchange_code=str(account_row.get("exchange_code") or ""),
                api_key=str(account_row.get("api_key") or ""),
                api_secret=str(account_row.get("api_secret") or ""),
                api_passphrase=str(account_row.get("api_passphrase") or ""),
            )
        )
        try:
            if market_type == "spot":
                balance = client.fetch_balance()
                return AccountHoldingSnapshot(
                    account_id=int(account_row["id"]),
                    market_type=market_type,
                    synced_at=datetime.now(),
                    spot_balances=self._extract_spot_balances(balance),
                    swap_positions={},
                )

            positions = []
            if client.has.get("fetchPositions"):
                positions = list(client.fetch_positions() or [])
            if not positions and client.has.get("fetchBalance"):
                balance = client.fetch_balance()
                positions = self._extract_positions_from_balance(balance)

            return AccountHoldingSnapshot(
                account_id=int(account_row["id"]),
                market_type=market_type,
                synced_at=datetime.now(),
                spot_balances={},
                swap_positions=self._extract_swap_positions(positions),
            )
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _extract_spot_balances(self, balance: Any) -> Dict[str, float]:
        result: Dict[str, float] = {}
        if not isinstance(balance, dict):
            return result

        total_balances = balance.get("total")
        if isinstance(total_balances, dict):
            for asset, value in total_balances.items():
                quantity = self._parse_float(value)
                if quantity > 0:
                    result[str(asset).upper()] = quantity
            if result:
                return result

        free_balances = balance.get("free")
        if isinstance(free_balances, dict):
            for asset, value in free_balances.items():
                quantity = self._parse_float(value)
                if quantity > 0:
                    result[str(asset).upper()] = quantity
        return result

    def _extract_swap_positions(self, positions: List[Dict[str, Any]]) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for position in positions:
            if not isinstance(position, dict):
                continue
            symbol = str(position.get("symbol") or "").strip()
            if not symbol:
                continue
            quantity = self._extract_position_quantity(position)
            if quantity <= 0:
                continue
            result[symbol] = quantity
        return result

    def _extract_positions_from_balance(self, balance: Any) -> List[Dict[str, Any]]:
        if not isinstance(balance, dict):
            return []
        info = balance.get("info")
        if isinstance(info, dict):
            if isinstance(info.get("positions"), list):
                return [item for item in info["positions"] if isinstance(item, dict)]
            if isinstance(info.get("data"), list):
                return [item for item in info["data"] if isinstance(item, dict)]
        return []

    def _extract_position_quantity(self, position: Dict[str, Any]) -> float:
        contracts = self._parse_float(position.get("contracts"))
        contract_size = self._parse_float(position.get("contractSize")) or 1.0
        if contracts > 0:
            return abs(contracts) * contract_size

        info = position.get("info")
        if isinstance(info, dict):
            for key in ("positionAmt", "pos", "size", "total", "holdVol"):
                quantity = self._parse_float(info.get(key))
                if quantity > 0:
                    return abs(quantity)

        for key in ("amount", "size", "total", "contracts"):
            quantity = self._parse_float(position.get(key))
            if quantity > 0:
                return abs(quantity)
        return 0.0

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

    def _parse_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


account_holding_service = AccountHoldingService()
