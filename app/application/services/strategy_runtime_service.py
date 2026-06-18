"""Read-side service for runtime strategy monitoring payloads."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.application.services.arbitrage_execution_plan_service import arbitrage_execution_plan_service
from app.application.services.opportunity_status_service import opportunity_status_service
from app.application.services.strategy_runtime_monitor_service import strategy_runtime_monitor_service
from app.infrastructure.cache import market_runtime_cache
from app.infrastructure.persistence import arbitrage_execution_repository
from app.shared.exceptions import AccountNotFoundError, AccountValidationError


EXPECTED_SUMMARY_CARD_KEYS = {
    "active_pairs",
    "active_orders",
    "history_orders",
    "candidate_count",
    "planned_amount",
}


class StrategyRuntimeService:
    def get_positions_orders_payload(self, user_id: int) -> Dict[str, object]:
        payload = dict(opportunity_status_service.build_strategy_payload(user_id=user_id))
        monitor_tables = strategy_runtime_monitor_service.build_monitor_tables(user_id=user_id)

        raw_active_positions_rows = list(monitor_tables.get("active_positions_rows") or [])
        active_positions_rows = self._build_monitor_position_rows(
            user_id=user_id,
            active_positions_rows=raw_active_positions_rows,
        )
        active_order_rows = list(monitor_tables.get("active_order_rows") or [])
        history_order_rows = list(monitor_tables.get("history_order_rows") or [])

        payload["active_positions_rows"] = active_positions_rows
        payload["active_order_rows"] = active_order_rows
        payload["history_order_rows"] = history_order_rows

        candidate_rows = list(payload.get("candidate_rows") or [])
        if candidate_rows or active_positions_rows or active_order_rows or history_order_rows:
            summary_cards = self._build_summary_cards(
                candidate_rows=candidate_rows,
                active_positions_rows=active_positions_rows,
                active_order_rows=active_order_rows,
                history_order_rows=history_order_rows,
            )
        else:
            summary_cards = self._empty_summary_cards()
        payload["summary_cards"] = summary_cards
        return payload

    def request_close_execution(self, *, user_id: int, execution_id: int) -> Dict[str, object]:
        execution_row = arbitrage_execution_repository.get_execution_by_id(execution_id)
        if execution_row is None or int(execution_row.get("user_id") or 0) != user_id:
            raise AccountNotFoundError("未找到对应的套利组合。")

        if str(execution_row.get("action") or "").strip().lower() != "open":
            raise AccountValidationError("当前记录不是可平仓的开仓组合。")

        current_status = str(execution_row.get("status") or "").strip().lower()
        if current_status == "closed":
            raise AccountValidationError("该组合已经完成平仓。")

        existing_close = arbitrage_execution_repository.get_latest_close_execution_by_source(
            source_execution_id=execution_id,
        )
        existing_close_status = str((existing_close or {}).get("status") or "").strip().lower()
        active_close_statuses = {"pending", "created", "processing", "opening", "open", "closing"}
        if existing_close is not None and existing_close_status in active_close_statuses:
            if current_status != "closing":
                arbitrage_execution_repository.update_execution_status(
                    execution_id=execution_id,
                    status="closing",
                )
            return {
                "already_pending": True,
                "close_execution_id": int(existing_close.get("id") or 0),
            }

        result = arbitrage_execution_plan_service.create_close_execution(
            execution_row=execution_row,
            reason="用户手动点击一键平仓",
        )
        if result is None:
            raise AccountValidationError("当前没有可用持仓可平，无法发起一键平仓。")

        arbitrage_execution_repository.update_execution_status(
            execution_id=execution_id,
            status="closing",
        )
        return {
            "already_pending": False,
            "close_execution_id": int(result.execution_id or 0),
        }

    def _has_expected_summary_cards(self, cards: Iterable[Dict[str, Any]]) -> bool:
        keys = {
            str(card.get("key") or "").strip()
            for card in cards
            if isinstance(card, dict)
        }
        return EXPECTED_SUMMARY_CARD_KEYS.issubset(keys)

    def _build_summary_cards(
        self,
        *,
        candidate_rows: List[Dict[str, Any]],
        active_positions_rows: List[Dict[str, Any]],
        active_order_rows: List[Dict[str, Any]],
        history_order_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        funding_count = sum(1 for item in candidate_rows if str(item.get("strategy_type") or "") == "funding")
        spread_count = sum(1 for item in candidate_rows if str(item.get("strategy_type") or "") == "spread")
        total_planned_amount = sum(float(item.get("planned_order_amount") or 0) for item in candidate_rows)

        return [
            {
                "key": "active_pairs",
                "label": "套利中组合",
                "value": str(len(active_positions_rows)),
                "change": "正在监控中的真实持仓套利组合",
                "tone": "positive" if active_positions_rows else "neutral",
            },
            {
                "key": "active_orders",
                "label": "当前挂单订单",
                "value": str(len(active_order_rows)),
                "change": "后台线程会继续提交、盯单、撤单重挂和状态回写",
                "tone": "warning" if active_order_rows else "neutral",
            },
            {
                "key": "history_orders",
                "label": "历史订单",
                "value": str(len(history_order_rows)),
                "change": "已结束订单和真实成交回报的本地记录",
                "tone": "brand" if history_order_rows else "neutral",
            },
            {
                "key": "candidate_count",
                "label": "规则命中候选",
                "value": str(len(candidate_rows)),
                "change": f"资金费 {funding_count} / 价差 {spread_count}",
                "tone": "brand",
            },
            {
                "key": "planned_amount",
                "label": "计划下单资金",
                "value": self._format_money(total_planned_amount),
                "change": "由当前命中的策略候选按单笔金额汇总",
                "tone": "positive" if total_planned_amount > 0 else "neutral",
            },
        ]

    def _empty_summary_cards(self) -> List[Dict[str, str]]:
        return [
            {
                "key": "active_pairs",
                "label": "套利中组合",
                "value": "0",
                "change": "当前还没有进入真实持仓中的套利组合",
                "tone": "neutral",
            },
            {
                "key": "active_orders",
                "label": "当前挂单订单",
                "value": "0",
                "change": "当前还没有正在提交或等待成交的实际订单",
                "tone": "neutral",
            },
            {
                "key": "history_orders",
                "label": "历史订单",
                "value": "0",
                "change": "当前还没有历史订单回报记录",
                "tone": "neutral",
            },
            {
                "key": "candidate_count",
                "label": "规则命中候选",
                "value": "0",
                "change": "等待规则与机会数据进入运行链路",
                "tone": "neutral",
            },
            {
                "key": "planned_amount",
                "label": "计划下单资金",
                "value": "$0",
                "change": "尚未生成需要执行的候选计划",
                "tone": "neutral",
            },
        ]

    def _build_monitor_position_rows(
        self,
        *,
        user_id: int,
        active_positions_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for index, row in enumerate(active_positions_rows, start=1):
            execution_id = self._parse_int(row.get("execution_id"))
            execution_row = (
                arbitrage_execution_repository.get_execution_by_id(execution_id)
                if execution_id > 0
                else None
            )
            strategy_type = str((execution_row or {}).get("strategy_type") or "").strip().lower()
            opportunity = self._find_runtime_opportunity(
                user_id=user_id,
                strategy_type=strategy_type,
                pair_key=str((row.get("pair_key") or (execution_row or {}).get("pair_key") or "")),
            )

            symbol = str(row.get("symbol") or self._base_asset_from_symbol(str((execution_row or {}).get("symbol") or "")) or "--")
            left_exchange = self._exchange_display(
                str(
                    (opportunity or {}).get("long_exchange")
                    or (opportunity or {}).get("buy_exchange")
                    or row.get("left_exchange")
                    or (execution_row or {}).get("left_exchange_code")
                    or "--"
                )
            )
            right_exchange = self._exchange_display(
                str(
                    (opportunity or {}).get("short_exchange")
                    or (opportunity or {}).get("sell_exchange")
                    or row.get("right_exchange")
                    or (execution_row or {}).get("right_exchange_code")
                    or "--"
                )
            )

            is_funding = strategy_type == "funding"
            pair_primary_text = (
                f"做多 {symbol}/USDT / {left_exchange}"
                if is_funding
                else f"买入 {symbol}/USDT / {left_exchange}"
            )
            pair_secondary_text = (
                f"做空 {symbol}/USDT / {right_exchange}"
                if is_funding
                else f"卖出 {symbol}/USDT / {right_exchange}"
            )

            if is_funding:
                net_spread = str((opportunity or {}).get("spread") or "--")
                net_rate = str((opportunity or {}).get("net_rate") or "--")
                current_price_primary = f"{left_exchange} {str((opportunity or {}).get('avg_long') or '--')}"
                current_price_secondary = f"{right_exchange} {str((opportunity or {}).get('avg_short') or '--')}"
                funding_rate_primary = f"{left_exchange} {str((opportunity or {}).get('long_funding_rate') or '--')}"
                funding_rate_secondary = f"{right_exchange} {str((opportunity or {}).get('short_funding_rate') or '--')}"
                fee_rate_primary = f"{left_exchange} {str((opportunity or {}).get('long_fee_rate') or '--')}"
                fee_rate_secondary = f"{right_exchange} {str((opportunity or {}).get('short_fee_rate') or '--')}"
                key_field_value = str((opportunity or {}).get("settlement") or row.get("updated_at") or "--")
                key_field_label = "距离结算" if opportunity is not None else "更新时间"
                type_label = "资金费套利"
                type_tone = "brand"
            else:
                net_spread = str((opportunity or {}).get("net_spread") or "--")
                net_rate = str((opportunity or {}).get("net_rate") or "--")
                current_price_primary = f"{left_exchange} {str((opportunity or {}).get('avg_long') or '--')}"
                current_price_secondary = f"{right_exchange} {str((opportunity or {}).get('avg_short') or '--')}"
                funding_rate_primary = f"{left_exchange} {str((opportunity or {}).get('buy_funding_rate') or '--')}"
                funding_rate_secondary = f"{right_exchange} {str((opportunity or {}).get('sell_funding_rate') or '--')}"
                fee_rate_primary = f"{left_exchange} {str((opportunity or {}).get('buy_fee_rate') or '--')}"
                fee_rate_secondary = f"{right_exchange} {str((opportunity or {}).get('sell_fee_rate') or '--')}"
                key_field_value = str((opportunity or {}).get("opportunity_time") or row.get("updated_at") or "--")
                key_field_label = "机会时间" if opportunity is not None else "更新时间"
                type_label = "价差套利"
                type_tone = "positive"

            position_qty_primary, position_qty_secondary = self._split_pair_value(str(row.get("position_qty") or "-- / --"))
            position_value_primary, position_value_secondary = self._split_pair_value(str(row.get("position_value") or "-- / --"))
            status = str(row.get("status") or "--")
            status_normalized = status.strip().lower()

            result.append(
                {
                    "rank": index,
                    "execution_id": execution_id,
                    "symbol": symbol,
                    "type_label": type_label,
                    "type_tone": type_tone,
                    "pair_primary_text": pair_primary_text,
                    "pair_secondary_text": pair_secondary_text,
                    "net_spread": net_spread,
                    "net_rate": net_rate,
                    "current_price_primary": current_price_primary,
                    "current_price_secondary": current_price_secondary,
                    "funding_rate_primary": funding_rate_primary,
                    "funding_rate_secondary": funding_rate_secondary,
                    "fee_rate_primary": fee_rate_primary,
                    "fee_rate_secondary": fee_rate_secondary,
                    "position_qty_primary": position_qty_primary,
                    "position_qty_secondary": position_qty_secondary,
                    "position_value_primary": position_value_primary,
                    "position_value_secondary": position_value_secondary,
                    "key_field_value": key_field_value,
                    "key_field_label": key_field_label,
                    "status": status,
                    "status_tone": str(row.get("status_tone") or "brand"),
                    "close_button_text": "平仓中" if "平仓中" in status or status_normalized == "closing" else "一键平仓",
                    "can_close": execution_id > 0 and "平仓中" not in status and status_normalized != "closing",
                    "entry_progress": str(row.get("entry_progress") or "--"),
                    "floating_pnl": str(row.get("floating_pnl") or "$0"),
                    "realized_pnl": str(row.get("realized_pnl") or "$0"),
                }
            )
        return result

    def _find_runtime_opportunity(self, *, user_id: int, strategy_type: str, pair_key: str) -> Dict[str, Any] | None:
        if not strategy_type or not pair_key:
            return None
        state = market_runtime_cache.get_user_rows_state(strategy_type, user_id)
        rows: List[Dict[str, Any]] = list(state.rows) if state is not None else []
        for row in rows:
            market_pair_key = str(row.get("market_pair_key") or "").strip().lower()
            if market_pair_key and pair_key.endswith(market_pair_key):
                return row
        return None

    def _split_pair_value(self, value: str) -> tuple[str, str]:
        if " / " in value:
            left, right = value.split(" / ", 1)
            return left.strip() or "--", right.strip() or "--"
        return value or "--", "--"

    def _exchange_display(self, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return "--"
        lowered = normalized.lower()
        mapping = {
            "gate": "Gate",
            "gateio": "Gate",
            "htx": "HTX",
            "okx": "OKX",
            "binance": "Binance",
        }
        return mapping.get(lowered, normalized.upper() if lowered == normalized else normalized)

    def _base_asset_from_symbol(self, symbol: str) -> str:
        text = str(symbol or "").strip().upper()
        if "/" in text:
            return text.split("/", 1)[0]
        if text.endswith("USDT"):
            return text[:-4]
        return text

    def _parse_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _format_money(self, value: float) -> str:
        return f"${float(value or 0):,.2f}".rstrip("0").rstrip(".")


strategy_runtime_service = StrategyRuntimeService()
