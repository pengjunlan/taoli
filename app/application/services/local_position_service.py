"""Local order, fill and position read/write service for arbitrage runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.infrastructure.persistence import arbitrage_execution_repository
from app.shared.utils.formatters import format_usd_compact


class LocalPositionService:
    def enrich_opportunity_rows(self, *, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        enriched: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            left_quantity = self._resolve_leg_quantity(
                account_id=item.get("left_account_id"),
                market_type=str(item.get("left_market_type") or ""),
                symbol=str(item.get("left_symbol_raw") or ""),
                position_side=self._left_position_side(item),
            )
            right_quantity = self._resolve_leg_quantity(
                account_id=item.get("right_account_id"),
                market_type=str(item.get("right_market_type") or ""),
                symbol=str(item.get("right_symbol_raw") or ""),
                position_side=self._right_position_side(item),
            )
            if left_quantity is not None:
                item["qty_long"] = self._format_quantity(left_quantity, str(item.get("symbol") or ""))
                item["value_long"] = self._format_value(left_quantity, self._parse_float(item.get("left_price_value")))
            if right_quantity is not None:
                item["qty_short"] = self._format_quantity(right_quantity, str(item.get("symbol") or ""))
                item["value_short"] = self._format_value(right_quantity, self._parse_float(item.get("right_price_value")))
            enriched.append(item)
        return enriched

    def build_runtime_tables(self, *, user_id: int, candidates: List[Dict[str, object]]) -> Dict[str, object]:
        order_rows = self._build_order_rows(user_id=user_id, fallback_candidates=candidates)
        fill_rows = self._build_fill_rows(user_id=user_id)
        positions_rows = self._build_position_rows(user_id=user_id, fallback_candidates=candidates)
        return {
            "positions_rows": positions_rows,
            "order_rows": order_rows,
            "fill_rows": fill_rows,
        }

    def _build_position_rows(self, *, user_id: int, fallback_candidates: List[Dict[str, object]]) -> List[Dict[str, str]]:
        positions = arbitrage_execution_repository.list_open_positions_for_user(user_id=user_id, limit=20)
        if positions:
            rows: List[Dict[str, str]] = []
            for position in positions:
                side = str(position.get("position_side") or "net").lower()
                exchange = str(position.get("exchange_code") or "--").upper()
                quantity = self._parse_float(position.get("quantity"))
                market_value = self._parse_float(position.get("market_value_usdt"))
                pnl = self._parse_float(position.get("unrealized_pnl_usdt"))
                rows.append(
                    {
                        "symbol": str(position.get("symbol") or "--").replace("/", ""),
                        "strategy": str(position.get("strategy_rule_name") or "--"),
                        "long_exchange": exchange if side in {"long", "net"} else "--",
                        "short_exchange": exchange if side == "short" else "--",
                        "size": self._format_quantity(quantity, self._base_asset_from_symbol(str(position.get("symbol") or ""))),
                        "hedge": "本地持仓",
                        "pnl": self._format_pnl(pnl),
                        "status": "持仓中",
                        "reason": f"持仓市值 {self._format_value_display(market_value)} / 均价 {self._format_price(self._parse_float(position.get('avg_entry_price')))}",
                    }
                )
            return rows

        if not fallback_candidates:
            return []

        rows: List[Dict[str, str]] = []
        for candidate in fallback_candidates[:10]:
            rows.append(
                {
                    "symbol": f"{candidate['symbol']}USDT",
                    "strategy": str(candidate["rule_name"]),
                    "long_exchange": str(candidate["open_exchange"]),
                    "short_exchange": str(candidate["hedge_exchange"]),
                    "size": str(candidate["position_size_text"]),
                    "hedge": "待成交确认",
                    "pnl": "--",
                    "status": str(candidate["status_label"]),
                    "reason": str(candidate["reason"]),
                }
            )
        return rows

    def _build_order_rows(self, *, user_id: int, fallback_candidates: List[Dict[str, object]]) -> List[Dict[str, str]]:
        order_legs = arbitrage_execution_repository.list_recent_order_legs_for_user(user_id=user_id, limit=20)
        if order_legs:
            rows: List[Dict[str, str]] = []
            for leg in order_legs:
                time_value = self._format_time(
                    leg.get("submitted_at") or leg.get("acknowledged_at") or leg.get("created_at")
                )
                rows.append(
                    {
                        "time": time_value,
                        "symbol": str(leg.get("symbol") or "--").replace("/", ""),
                        "exchange": str(leg.get("exchange_code") or "--").upper(),
                        "side": self._format_side(
                            market_type=str(leg.get("market_type") or ""),
                            side=str(leg.get("side") or ""),
                            leg_role="",
                        ),
                        "status": self._format_order_status(str(leg.get("status") or "")),
                        "size": self._format_value_display(float(leg.get("requested_value_usdt") or 0)),
                        "strategy": str(leg.get("strategy_rule_name") or "--"),
                        "reason": str(leg.get("trigger_reason") or leg.get("status_message") or "--"),
                        "status_tone": self._status_tone(str(leg.get("status") or "")),
                    }
                )
            return rows

        now_text = datetime.now().strftime("%H:%M:%S")
        rows: List[Dict[str, str]] = []
        for candidate in fallback_candidates[:20]:
            rows.append(
                {
                    "time": now_text,
                    "symbol": f"{candidate['symbol']}USDT",
                    "exchange": str(candidate["open_exchange"]),
                    "side": str(candidate["action_label"]),
                    "status": str(candidate["status_label"]),
                    "size": str(candidate["position_size_text"]),
                    "strategy": str(candidate["rule_name"]),
                    "reason": str(candidate["reason"]),
                    "status_tone": str(candidate["status_tone"]),
                }
            )
        return rows

    def _build_fill_rows(self, *, user_id: int) -> List[Dict[str, str]]:
        fills = arbitrage_execution_repository.list_recent_fill_records_for_user(user_id=user_id, limit=20)
        rows: List[Dict[str, str]] = []
        for fill in fills:
            rows.append(
                {
                    "time": self._format_time(fill.get("filled_at") or fill.get("created_at")),
                    "symbol": str(fill.get("symbol") or "--").replace("/", ""),
                    "exchange": str(fill.get("exchange_code") or "--").upper(),
                    "side": self._format_side(
                        market_type=str(fill.get("market_type") or ""),
                        side=str(fill.get("side") or ""),
                        leg_role="",
                    ),
                    "price": self._format_price(float(fill.get("fill_price") or 0)),
                    "size": self._format_value_display(float(fill.get("fill_value_usdt") or 0)),
                }
            )
        return rows

    def _resolve_leg_quantity(
        self,
        *,
        account_id: Any,
        market_type: str,
        symbol: str,
        position_side: str,
    ) -> Optional[float]:
        try:
            account_id_int = int(account_id or 0)
        except (TypeError, ValueError):
            return None
        if account_id_int <= 0 or not market_type or not symbol:
            return None
        return arbitrage_execution_repository.get_position_quantity(
            exchange_account_id=account_id_int,
            market_type=market_type,
            symbol=symbol,
            position_side=position_side,
        )

    def _left_position_side(self, row: Dict[str, Any]) -> str:
        if "buy_exchange" in row:
            return "long"
        return "long"

    def _right_position_side(self, row: Dict[str, Any]) -> str:
        if "sell_exchange" in row:
            return "short"
        return "short"

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

    def _format_value_display(self, value: float) -> str:
        if value <= 0:
            return "$0"
        return format_usd_compact(value)

    def _format_price(self, price: float) -> str:
        if price <= 0:
            return "--"
        if price >= 1000:
            return f"{price:,.0f}"
        if price >= 1:
            return f"{price:,.2f}".rstrip("0").rstrip(".")
        return f"{price:,.4f}".rstrip("0").rstrip(".")

    def _format_time(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%H:%M:%S")
        return "--"

    def _format_order_status(self, status: str) -> str:
        mapping = {
            "pending": "待提交",
            "created": "已创建",
            "submitting": "提交中",
            "submitted": "已提交",
            "acknowledged": "已受理",
            "partial": "部分成交",
            "filled": "已成交",
            "cancelled": "已取消",
            "failed": "失败",
        }
        return mapping.get(status, status or "--")

    def _status_tone(self, status: str) -> str:
        normalized = status.strip().lower()
        if normalized in {"filled", "acknowledged", "submitted"}:
            return "positive"
        if normalized in {"failed", "cancelled"}:
            return "negative"
        return "warning"

    def _format_side(self, *, market_type: str, side: str, leg_role: str) -> str:
        market = market_type.strip().lower()
        normalized_side = side.strip().lower()
        role = leg_role.strip().lower()
        if market == "swap":
            if normalized_side == "buy":
                return "开多" if role != "hedge" else "平空"
            if normalized_side == "sell":
                return "开空" if role == "hedge" or role == "short" else "平多"
        return "买入" if normalized_side == "buy" else "卖出"

    def _format_pnl(self, value: float) -> str:
        if value > 0:
            return f"+{format_usd_compact(value)}"
        if value < 0:
            return f"-{format_usd_compact(abs(value))}"
        return "$0"

    def _base_asset_from_symbol(self, symbol: str) -> str:
        text = symbol.strip().upper()
        if "/" in text:
            return text.split("/", 1)[0]
        if text.endswith("USDT"):
            return text[:-4]
        return text

    def _parse_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


local_position_service = LocalPositionService()
