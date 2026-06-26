"""Aggregate runtime monitoring payloads for active arbitrage positions and orders."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List

from app.application.services.arbitrage_runtime_support_service import arbitrage_runtime_support_service
from app.infrastructure.cache import market_runtime_cache
from app.infrastructure.persistence import arbitrage_execution_repository
from app.shared.utils.formatters import format_usd_compact


class StrategyRuntimeMonitorService:
    def build_monitor_tables(self, *, user_id: int) -> Dict[str, List[Dict[str, str]]]:
        active_executions = arbitrage_execution_repository.list_active_open_executions_for_user(
            user_id=user_id,
            limit=200,
        )
        recent_order_legs = arbitrage_execution_repository.list_recent_order_legs_for_user(
            user_id=user_id,
            limit=120,
        )
        recent_fills = arbitrage_execution_repository.list_recent_fill_records_for_user(
            user_id=user_id,
            limit=120,
        )
        open_positions = arbitrage_execution_repository.list_open_positions_for_user(
            user_id=user_id,
            limit=120,
        )
        active_executions = self._merge_executions_with_open_positions(
            user_id=user_id,
            active_executions=active_executions,
            open_positions=open_positions,
        )

        positions_rows = self._build_active_pair_rows(
            active_executions=active_executions,
            order_legs=recent_order_legs,
            open_positions=open_positions,
        )
        pending_order_rows = self._build_pending_order_rows(recent_order_legs)
        actual_order_rows = self._build_actual_order_rows(recent_order_legs)
        active_order_rows = pending_order_rows + actual_order_rows
        history_order_rows = self._build_history_order_rows(recent_order_legs, recent_fills)
        return {
            "active_positions_rows": positions_rows,
            "pending_order_rows": pending_order_rows,
            "actual_order_rows": actual_order_rows,
            "active_order_rows": active_order_rows,
            "history_order_rows": history_order_rows,
        }

    def _build_active_pair_rows(
        self,
        *,
        active_executions: List[Dict[str, Any]],
        order_legs: List[Dict[str, Any]],
        open_positions: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        legs_by_execution: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in order_legs:
            execution_id = int(row.get("execution_id") or 0)
            if execution_id > 0:
                legs_by_execution[execution_id].append(row)

        positions_by_execution: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in open_positions:
            execution_id = self._position_execution_id(row)
            if execution_id > 0:
                positions_by_execution[execution_id].append(row)

        rows: List[Dict[str, str]] = []
        for execution in active_executions:
            execution_id = int(execution.get("id") or 0)
            if execution_id <= 0:
                continue

            execution_legs = legs_by_execution.get(execution_id, [])
            execution_positions = positions_by_execution.get(execution_id, [])
            left_leg = next((row for row in execution_legs if str(row.get("leg_role") or "") == "left"), None)
            right_leg = next((row for row in execution_legs if str(row.get("leg_role") or "") == "right"), None)
            left_position = self._match_position(
                execution_positions,
                exchange_code=str(execution.get("left_exchange_code") or ""),
                market_type=str(execution.get("left_market_type") or ""),
                symbol=str(execution.get("left_symbol") or ""),
                position_side="long",
            )
            right_position = self._match_position(
                execution_positions,
                exchange_code=str(execution.get("right_exchange_code") or ""),
                market_type=str(execution.get("right_market_type") or ""),
                symbol=str(execution.get("right_symbol") or ""),
                position_side="short",
            )

            left_quantity = self._parse_float((left_position or {}).get("quantity"))
            right_quantity = self._parse_float((right_position or {}).get("quantity"))
            left_avg_price = self._parse_float((left_position or {}).get("avg_entry_price"))
            right_avg_price = self._parse_float((right_position or {}).get("avg_entry_price"))

            left_current_price = self._resolve_latest_price(
                exchange_code=str(execution.get("left_exchange_code") or ""),
                market_type=str(execution.get("left_market_type") or ""),
                symbol=str(execution.get("left_symbol") or ""),
                fallback=self._parse_float((left_position or {}).get("mark_price")),
            )
            right_current_price = self._resolve_latest_price(
                exchange_code=str(execution.get("right_exchange_code") or ""),
                market_type=str(execution.get("right_market_type") or ""),
                symbol=str(execution.get("right_symbol") or ""),
                fallback=self._parse_float((right_position or {}).get("mark_price")),
            )

            unrealized_left = self._calc_unrealized_long(left_quantity, left_avg_price, left_current_price)
            unrealized_right = self._calc_unrealized_short(right_quantity, right_avg_price, right_current_price)
            realized_left = self._parse_float((left_position or {}).get("realized_pnl_usdt"))
            realized_right = self._parse_float((right_position or {}).get("realized_pnl_usdt"))

            pair_status = str(execution.get("status") or "--")
            has_live_position = left_quantity > 0 or right_quantity > 0
            has_active_order = any(
                str(row.get("status") or "").strip().lower() in {"pending", "created", "submitting", "submitted", "partial"}
                for row in execution_legs
            )
            if not has_live_position and (pair_status != "closing" or not has_active_order):
                continue
            rows.append(
                {
                    "row_code": self._build_position_row_code(execution),
                    "execution_id": str(execution_id),
                    "pair_key": str(execution.get("pair_key") or ""),
                    "symbol": str(execution.get("symbol") or "--"),
                    "strategy": str(execution.get("strategy_rule_name") or "--"),
                    "pair_type": self._strategy_label(str(execution.get("strategy_type") or "")),
                    "left_exchange": str(execution.get("left_exchange_code") or "--").upper(),
                    "right_exchange": str(execution.get("right_exchange_code") or "--").upper(),
                    "position_qty": self._format_dual_quantity(left_quantity, right_quantity, str(execution.get("base_asset") or "")),
                    "avg_entry_price": self._format_dual_price(left_avg_price, right_avg_price),
                    "current_price": self._format_dual_price(left_current_price, right_current_price),
                    "position_value": self._format_dual_value(
                        left_quantity * left_current_price if left_quantity > 0 and left_current_price > 0 else 0.0,
                        right_quantity * right_current_price if right_quantity > 0 and right_current_price > 0 else 0.0,
                    ),
                    "floating_pnl": self._format_signed_value(unrealized_left + unrealized_right),
                    "realized_pnl": self._format_signed_value(realized_left + realized_right),
                    "status": self._format_execution_status(pair_status),
                    "status_tone": self._status_tone(pair_status),
                    "updated_at": self._format_datetime(execution.get("updated_at")),
                    "entry_progress": self._build_entry_progress(left_leg, right_leg),
                }
            )

        return rows

    def _merge_executions_with_open_positions(
        self,
        *,
        user_id: int,
        active_executions: List[Dict[str, Any]],
        open_positions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        known_execution_ids = {
            int(row.get("id") or 0)
            for row in active_executions
            if int(row.get("id") or 0) > 0
        }
        merged_rows = list(active_executions)

        for row in open_positions:
            execution_id = self._position_execution_id(row)
            if execution_id <= 0 or execution_id in known_execution_ids:
                continue
            execution_row = arbitrage_execution_repository.get_execution_by_id(execution_id)
            if execution_row is None:
                continue
            if int(execution_row.get("user_id") or 0) != user_id:
                continue
            merged_rows.append(execution_row)
            known_execution_ids.add(execution_id)

        merged_rows.sort(
            key=lambda row: (
                self._safe_datetime(row.get("updated_at")),
                int(row.get("id") or 0),
            ),
            reverse=True,
        )
        return merged_rows

    def _build_pending_order_rows(self, order_legs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        active_statuses = {"pending", "created", "submitting", "submitted", "partial"}
        rows: List[Dict[str, str]] = []
        for row in order_legs:
            status = str(row.get("status") or "").strip().lower()
            if status not in active_statuses:
                continue
            if str(row.get("exchange_order_id") or "").strip():
                continue
            rows.append(self._build_active_order_row(row, status=status))
        return rows

    def _build_actual_order_rows(self, order_legs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        active_statuses = {"pending", "created", "submitting", "submitted", "partial"}
        rows: List[Dict[str, str]] = []
        for row in order_legs:
            status = str(row.get("status") or "").strip().lower()
            if status not in active_statuses:
                continue
            if not str(row.get("exchange_order_id") or "").strip():
                continue
            rows.append(self._build_active_order_row(row, status=status))
        return rows

    def _build_active_order_row(self, row: Dict[str, Any], *, status: str) -> Dict[str, str]:
        return {
            "row_code": self._build_order_row_code(row),
            "time": self._format_time(row.get("submitted_at") or row.get("acknowledged_at") or row.get("created_at")),
            "symbol": str(row.get("symbol") or "--").replace("/", ""),
            "strategy": str(row.get("strategy_rule_name") or "--"),
            "pair_key": str(row.get("pair_key") or ""),
            "exchange": str(row.get("exchange_code") or "--").upper(),
            "leg_role": self._format_leg_role(str(row.get("leg_role") or "")),
            "action": self._format_side(str(row.get("side") or ""), str(row.get("position_side") or "")),
            "execution_action": self._format_execution_action(str(row.get("action") or "")),
            "status": self._format_order_status(status),
            "status_tone": self._status_tone(status),
            "requested_price": self._format_price(self._parse_float(row.get("requested_price"))),
            "requested_quantity": self._format_quantity(
                self._to_base_quantity(row, "requested_quantity"),
                self._base_asset_from_symbol(str(row.get("symbol") or "")),
            ),
            "filled_quantity": self._format_quantity(
                self._parse_float(row.get("filled_quantity")),
                self._base_asset_from_symbol(str(row.get("symbol") or "")),
            ),
            "requested_value": self._format_value_display(self._parse_float(row.get("requested_value_usdt"))),
            "filled_value": self._format_value_display(self._parse_float(row.get("filled_value_usdt"))),
            "retry_count": str(int(row.get("retry_count") or 0)),
            "reason": str(row.get("status_message") or row.get("trigger_reason") or "--"),
        }

    def _build_history_order_rows(
        self,
        order_legs: List[Dict[str, Any]],
        fill_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        fill_count_map: Dict[str, int] = defaultdict(int)
        for fill in fill_rows:
            key = self._history_order_key(
                order_leg_id=int(fill.get("order_leg_id") or 0),
                exchange_code=str(fill.get("exchange_code") or ""),
                symbol=str(fill.get("symbol") or ""),
                side=str(fill.get("side") or ""),
            )
            if key:
                fill_count_map[key] += 1

        rows: List[Dict[str, str]] = []
        for row in order_legs:
            status = str(row.get("status") or "").strip().lower()
            if status in {"pending", "created", "submitting", "submitted", "partial"}:
                continue
            history_key = self._history_order_key(
                order_leg_id=int(row.get("id") or 0),
                exchange_code=str(row.get("exchange_code") or ""),
                symbol=str(row.get("symbol") or ""),
                side=str(row.get("side") or ""),
            )
            close_type = self._resolve_close_type(row)
            rows.append(
                {
                    "row_code": self._build_order_row_code(row),
                    "time": self._format_time(row.get("closed_at") or row.get("acknowledged_at") or row.get("created_at")),
                    "symbol": str(row.get("symbol") or "--").replace("/", ""),
                    "strategy": str(row.get("strategy_rule_name") or "--"),
                    "pair_key": str(row.get("pair_key") or ""),
                    "exchange": str(row.get("exchange_code") or "--").upper(),
                    "leg_role": self._format_leg_role(str(row.get("leg_role") or "")),
                    "action": self._format_side(str(row.get("side") or ""), str(row.get("position_side") or "")),
                    "execution_action": self._format_execution_action(str(row.get("action") or "")),
                    "status": self._format_order_status(status),
                    "status_tone": self._status_tone(status),
                    "avg_fill_price": self._format_price(self._parse_float(row.get("average_fill_price"))),
                    "filled_quantity": self._format_quantity(
                        self._parse_float(row.get("filled_quantity")),
                        self._base_asset_from_symbol(str(row.get("symbol") or "")),
                    ),
                    "filled_value": self._format_value_display(self._parse_float(row.get("filled_value_usdt"))),
                    "fill_count": str(fill_count_map.get(history_key, 0)),
                    "close_type": close_type["key"],
                    "close_type_label": close_type["label"],
                    "close_type_tone": close_type["tone"],
                    "result": str(row.get("status_message") or "--"),
                }
            )
        return rows

    def _resolve_close_type(self, row: Dict[str, Any]) -> Dict[str, str]:
        execution_action = str(row.get("action") or "").strip().lower()
        status = str(row.get("status") or "").strip().lower()
        reason = f"{row.get('trigger_reason') or ''} {row.get('status_message') or ''}".lower()
        if execution_action != "close":
            return {"key": "open", "label": "开仓订单", "tone": self._status_tone(status)}
        if "止盈" in reason or "take_profit" in reason:
            return {"key": "take_profit", "label": "止盈平仓", "tone": "positive"}
        if "止损" in reason or "stop_loss" in reason or "超过最大价差" in reason or "最大资金费成本" in reason:
            return {"key": "stop_loss", "label": "止损平仓", "tone": "danger"}
        if "强制" in reason or "单腿" in reason or "暴露" in reason or "force" in reason:
            return {"key": "force_close", "label": "强制平仓", "tone": "danger"}
        if "一键" in reason or "手动" in reason or "manual" in reason:
            return {"key": "manual_close", "label": "手动平仓", "tone": "warning"}
        if "最大持有时间" in reason or "回落" in reason or "正常平仓" in reason:
            return {"key": "normal_close", "label": "正常平仓", "tone": "brand"}
        return {"key": "close", "label": "平仓订单", "tone": self._status_tone(status)}

    def _match_position(
        self,
        positions: Iterable[Dict[str, Any]],
        *,
        exchange_code: str,
        market_type: str,
        symbol: str,
        position_side: str,
    ) -> Dict[str, Any] | None:
        for row in positions:
            if str(row.get("exchange_code") or "").lower() != exchange_code.lower():
                continue
            if str(row.get("market_type") or "").lower() != market_type.lower():
                continue
            if str(row.get("symbol") or "") != symbol:
                continue
            if str(row.get("position_side") or "").lower() != position_side.lower():
                continue
            return row
        return None

    def _resolve_latest_price(self, *, exchange_code: str, market_type: str, symbol: str, fallback: float) -> float:
        ticker = market_runtime_cache.get_ticker(exchange_code, market_type, symbol)
        if ticker is None:
            return fallback
        return self._parse_float(ticker.last_price) or fallback

    def _to_base_quantity(self, row: Dict[str, Any], field_name: str) -> float:
        raw_value = self._parse_float(row.get(field_name))
        if raw_value <= 0:
            return 0.0
        return arbitrage_runtime_support_service.to_base_quantity(
            exchange_code=str(row.get("exchange_code") or ""),
            market_type=str(row.get("market_type") or ""),
            symbol=str(row.get("symbol") or ""),
            order_quantity=raw_value,
        )

    def _build_entry_progress(self, left_leg: Dict[str, Any] | None, right_leg: Dict[str, Any] | None) -> str:
        parts: List[str] = []
        if left_leg is not None:
            parts.append(f"左腿 {self._format_order_status(str(left_leg.get('status') or ''))}")
        if right_leg is not None:
            parts.append(f"右腿 {self._format_order_status(str(right_leg.get('status') or ''))}")
        return " / ".join(parts) if parts else "--"

    def _calc_unrealized_long(self, quantity: float, avg_price: float, current_price: float) -> float:
        if quantity <= 0 or avg_price <= 0 or current_price <= 0:
            return 0.0
        return (current_price - avg_price) * quantity

    def _calc_unrealized_short(self, quantity: float, avg_price: float, current_price: float) -> float:
        if quantity <= 0 or avg_price <= 0 or current_price <= 0:
            return 0.0
        return (avg_price - current_price) * quantity

    def _strategy_label(self, strategy_type: str) -> str:
        normalized = str(strategy_type or "").strip().lower()
        if normalized == "funding":
            return "资金费套利"
        if normalized == "spread":
            return "价差套利"
        return strategy_type or "--"

    def _format_leg_role(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "left":
            return "左腿"
        if normalized == "right":
            return "右腿"
        return value or "--"

    def _format_execution_action(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "open":
            return "开仓"
        if normalized == "close":
            return "平仓"
        return value or "--"

    def _format_execution_status(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        mapping = {
            "pending": "待开仓",
            "created": "已创建",
            "processing": "处理中",
            "opening": "开仓中",
            "open": "持仓中",
            "closing": "平仓中",
            "closed": "已平仓",
            "failed": "失败",
        }
        return mapping.get(normalized, value or "--")

    def _format_order_status(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        mapping = {
            "pending": "待提交",
            "created": "已创建",
            "submitting": "提交中",
            "submitted": "已挂单",
            "partial": "部分成交",
            "filled": "已成交",
            "cancelled": "已撤单",
            "failed": "失败",
        }
        return mapping.get(normalized, value or "--")

    def _status_tone(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"open", "filled", "closed"}:
            return "positive"
        if normalized in {"failed", "cancelled"}:
            return "negative"
        if normalized in {"closing"}:
            return "brand"
        return "warning"

    def _format_side(self, side: str, position_side: str) -> str:
        normalized_side = str(side or "").strip().lower()
        normalized_position_side = str(position_side or "").strip().lower()
        if normalized_position_side == "long":
            return "开多" if normalized_side == "buy" else "平多"
        if normalized_position_side == "short":
            return "开空" if normalized_side == "sell" else "平空"
        return "买入" if normalized_side == "buy" else "卖出"

    def _format_dual_quantity(self, left_value: float, right_value: float, base_asset: str) -> str:
        left_text = self._format_quantity(left_value, base_asset)
        right_text = self._format_quantity(right_value, base_asset)
        return f"{left_text} / {right_text}"

    def _format_dual_price(self, left_value: float, right_value: float) -> str:
        return f"{self._format_price(left_value)} / {self._format_price(right_value)}"

    def _format_dual_value(self, left_value: float, right_value: float) -> str:
        return f"{self._format_value_display(left_value)} / {self._format_value_display(right_value)}"

    def _format_quantity(self, value: float, base_asset: str) -> str:
        normalized_asset = str(base_asset or "").strip().upper()
        if value <= 0:
            return f"0.0000 {normalized_asset}".strip()
        if value >= 1000:
            text = f"{value:,.0f}"
        elif value >= 1:
            text = f"{value:,.2f}".rstrip("0").rstrip(".")
        else:
            text = f"{value:,.4f}".rstrip("0").rstrip(".")
        return f"{text} {normalized_asset}".strip()

    def _format_price(self, value: float) -> str:
        if value <= 0:
            return "--"
        if value >= 1000:
            return f"{value:,.0f}"
        if value >= 1:
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return f"{value:,.6f}".rstrip("0").rstrip(".")

    def _format_signed_value(self, value: float) -> str:
        formatted = self._format_value_display(abs(value))
        if value > 0:
            return f"+{formatted}"
        if value < 0:
            return f"-{formatted}"
        return "$0"

    def _format_value_display(self, value: float) -> str:
        if value <= 0:
            return "$0"
        if value < 0.01:
            return "<$0.01"
        if value < 1:
            return f"${value:.4f}".rstrip("0").rstrip(".")
        if value < 1000:
            return f"${value:,.2f}".rstrip("0").rstrip(".")
        return format_usd_compact(value)

    def _format_time(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%H:%M:%S")
        return "--"

    def _format_datetime(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return "--"

    def _base_asset_from_symbol(self, symbol: str) -> str:
        text = str(symbol or "").strip().upper()
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

    def _history_order_key(self, *, order_leg_id: int, exchange_code: str, symbol: str, side: str) -> str:
        if order_leg_id > 0:
            return f"leg:{order_leg_id}"
        if exchange_code or symbol or side:
            return f"{exchange_code}:{symbol}:{side}"
        return ""

    def _position_execution_id(self, row: Dict[str, Any]) -> int:
        return int(row.get("runtime_execution_id") or row.get("opened_by_execution_id") or 0)

    def _build_position_row_code(self, execution: Dict[str, Any]) -> str:
        execution_id = int(execution.get("id") or 0)
        pair_key = str(execution.get("pair_key") or "").strip()
        if execution_id > 0:
            return f"EXE-{execution_id}"
        if pair_key:
            return pair_key
        return "--"

    def _build_order_row_code(self, row: Dict[str, Any]) -> str:
        order_leg_id = int(row.get("id") or 0)
        execution_id = int(row.get("execution_id") or 0)
        if order_leg_id > 0:
            return f"LEG-{order_leg_id}"
        if execution_id > 0:
            return f"EXE-{execution_id}"
        pair_key = str(row.get("pair_key") or "").strip()
        if pair_key:
            return pair_key
        return "--"

    def _safe_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.min


strategy_runtime_monitor_service = StrategyRuntimeMonitorService()
