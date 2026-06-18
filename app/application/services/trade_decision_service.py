"""Runtime strategy decision service backed by real opportunity rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.application.services.opportunity_user_overlay_service import opportunity_user_overlay_service
from app.infrastructure.persistence.account_repository import account_repository
from app.application.services.local_position_service import local_position_service
from app.application.services.strategy_rule_runtime_service import strategy_rule_runtime_service
from app.application.services.strategy_runtime_monitor_service import strategy_runtime_monitor_service


class TradeDecisionService:
    def build_runtime_payload(
        self,
        *,
        user_id: int,
        strategy_rows: List[Dict[str, Any]],
        funding_rows: List[Dict[str, Any]],
        spread_rows: List[Dict[str, Any]],
    ) -> Dict[str, object]:
        enabled_rules = [row for row in strategy_rows if bool(row.get("is_enabled"))]
        funding_rules = [row for row in enabled_rules if str(row.get("strategy_type") or "") == "funding"]
        spread_rules = [row for row in enabled_rules if str(row.get("strategy_type") or "") == "spread"]
        funding_execution_rows = opportunity_user_overlay_service.enrich_execution_rows(
            user_id=user_id,
            channel="funding",
            rows=funding_rows,
        )
        spread_execution_rows = opportunity_user_overlay_service.enrich_execution_rows(
            user_id=user_id,
            channel="spread",
            rows=spread_rows,
        )

        candidates: List[Dict[str, object]] = []
        candidates.extend(self._build_funding_candidates(funding_execution_rows, funding_rules))
        candidates.extend(self._build_spread_candidates(spread_execution_rows, spread_rules))

        runtime_tables = local_position_service.build_runtime_tables(
            user_id=user_id,
            candidates=candidates,
        )
        monitor_tables = strategy_runtime_monitor_service.build_monitor_tables(user_id=user_id)
        positions_rows = list(runtime_tables.get("positions_rows") or [])
        order_rows = list(runtime_tables.get("order_rows") or [])
        fill_rows = list(runtime_tables.get("fill_rows") or [])
        active_positions_rows = list(monitor_tables.get("active_positions_rows") or [])
        active_order_rows = list(monitor_tables.get("active_order_rows") or [])
        history_order_rows = list(monitor_tables.get("history_order_rows") or [])
        summary_cards = self._build_summary_cards(
            candidates,
            positions_rows,
            order_rows,
            fill_rows,
            active_positions_rows,
            active_order_rows,
            history_order_rows,
        )

        return {
            "user_id": user_id,
            "generated_at": datetime.now(),
            "enabled_rule_count": len(enabled_rules),
            "account_count": len(account_repository.list_active_accounts_with_address_by_user_id(user_id)),
            "candidate_rows": candidates,
            "positions_rows": positions_rows,
            "order_rows": order_rows,
            "fill_rows": fill_rows,
            "active_positions_rows": active_positions_rows,
            "active_order_rows": active_order_rows,
            "history_order_rows": history_order_rows,
            "summary_cards": summary_cards,
        }

    def _build_funding_candidates(
        self,
        opportunity_rows: List[Dict[str, Any]],
        rule_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, object]]:
        if not opportunity_rows or not rule_rows:
            return []

        default_rule = rule_rows[0]
        result: List[Dict[str, object]] = []
        for rank, row in enumerate(opportunity_rows, start=1):
            if not bool(row.get("execution_ready")):
                continue
            net_rate = self._parse_float(row.get("net_rate_value"), fallback=row.get("net_rate"))
            price_diff = self._parse_float(row.get("price_diff_value"), fallback=row.get("price_diff"))
            matched_rule = next(
                (
                    rule
                    for rule in rule_rows
                    if net_rate > strategy_rule_runtime_service.build_runtime_view(rule).open_threshold
                    and (
                        strategy_rule_runtime_service.build_runtime_view(rule).stop_loss_price_diff <= 0
                        or price_diff <= strategy_rule_runtime_service.build_runtime_view(rule).stop_loss_price_diff
                    )
                ),
                None,
            )
            if matched_rule is None:
                continue

            runtime_rule = strategy_rule_runtime_service.build_runtime_view(matched_rule)
            order_amount = runtime_rule.order_amount_usdt
            max_position = runtime_rule.max_position_quantity
            result.append(
                {
                    "rank": rank,
                    "strategy_type": "funding",
                    "strategy_label": "资金费套利",
                    "rule_id": int(matched_rule.get("id") or 0),
                    "rule_name": str(matched_rule.get("name") or default_rule.get("name") or "资金费套利规则"),
                    "symbol": str(row.get("symbol") or "--"),
                    "open_exchange": str(row.get("long_exchange") or "--"),
                    "hedge_exchange": str(row.get("short_exchange") or "--"),
                    "primary_metric": str(row.get("net_rate") or "--"),
                    "secondary_metric": str(row.get("annual") or "--"),
                    "risk_metric": str(row.get("price_diff") or "--"),
                    "planned_order_amount": order_amount,
                    "max_position_usdt": max_position,
                    "max_position_quantity": max_position,
                    "order_interval_seconds": runtime_rule.order_interval_seconds,
                    "reason": (
                        f"命中规则 {matched_rule.get('name') or '--'}："
                        f"净资金费率 {row.get('net_rate') or '--'}，年化 {row.get('annual') or '--'}，"
                        f"价格差 {row.get('price_diff') or '--'}"
                    ),
                    "status": "candidate",
                    "status_label": "待执行评估",
                    "status_tone": "brand",
                    "action_label": "开资金费对冲",
                    "opportunity_time": str(row.get("settlement") or "--"),
                    "position_size_text": self._format_quantity(max_position, str(row.get("symbol") or "")),
                }
            )
        return result

    def _build_spread_candidates(
        self,
        opportunity_rows: List[Dict[str, Any]],
        rule_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, object]]:
        if not opportunity_rows or not rule_rows:
            return []

        default_rule = rule_rows[0]
        result: List[Dict[str, object]] = []
        for rank, row in enumerate(opportunity_rows, start=1):
            if not bool(row.get("execution_ready")):
                continue
            latest_spread = self._parse_float(row.get("latest_spread_value"), fallback=row.get("latest_spread"))
            price_diff = self._parse_float(row.get("price_diff_value"), fallback=row.get("price_diff"))
            matched_rule = next(
                (
                    rule
                    for rule in rule_rows
                    if latest_spread >= strategy_rule_runtime_service.build_runtime_view(rule).open_threshold
                    and (
                        strategy_rule_runtime_service.build_runtime_view(rule).stop_loss_price_diff <= 0
                        or price_diff <= strategy_rule_runtime_service.build_runtime_view(rule).stop_loss_price_diff
                    )
                ),
                None,
            )
            if matched_rule is None:
                continue

            runtime_rule = strategy_rule_runtime_service.build_runtime_view(matched_rule)
            order_amount = runtime_rule.order_amount_usdt
            max_position = runtime_rule.max_position_quantity
            result.append(
                {
                    "rank": rank,
                    "strategy_type": "spread",
                    "strategy_label": "价差套利",
                    "rule_id": int(matched_rule.get("id") or 0),
                    "rule_name": str(matched_rule.get("name") or default_rule.get("name") or "价差套利规则"),
                    "symbol": str(row.get("symbol") or "--"),
                    "open_exchange": str(row.get("buy_exchange") or "--"),
                    "hedge_exchange": str(row.get("sell_exchange") or "--"),
                    "primary_metric": str(row.get("latest_spread") or "--"),
                    "secondary_metric": str(row.get("net_spread") or "--"),
                    "risk_metric": str(row.get("price_diff") or "--"),
                    "planned_order_amount": order_amount,
                    "max_position_usdt": max_position,
                    "max_position_quantity": max_position,
                    "order_interval_seconds": runtime_rule.order_interval_seconds,
                    "reason": (
                        f"命中规则 {matched_rule.get('name') or '--'}："
                        f"最新价差 {row.get('latest_spread') or '--'}，净价差 {row.get('net_spread') or '--'}，价格差 {row.get('price_diff') or '--'}"
                    ),
                    "status": "candidate",
                    "status_label": "待执行评估",
                    "status_tone": "brand",
                    "action_label": "开价差对冲",
                    "opportunity_time": str(row.get("opportunity_time") or "--"),
                    "position_size_text": self._format_quantity(max_position, str(row.get("symbol") or "")),
                }
            )
        return result

    def _build_summary_cards(
        self,
        candidates: List[Dict[str, object]],
        positions_rows: List[Dict[str, str]],
        order_rows: List[Dict[str, str]],
        fill_rows: List[Dict[str, str]],
        active_positions_rows: List[Dict[str, str]],
        active_order_rows: List[Dict[str, str]],
        history_order_rows: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        funding_count = sum(1 for item in candidates if str(item.get("strategy_type") or "") == "funding")
        spread_count = sum(1 for item in candidates if str(item.get("strategy_type") or "") == "spread")
        total_planned_amount = sum(float(item.get("planned_order_amount") or 0) for item in candidates)

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
                "value": str(len(candidates)),
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

    def _parse_percent(self, value: object) -> float:
        text = str(value or "").replace("%", "").replace("+", "").replace(",", "").strip()
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _parse_float(self, value: object, *, fallback: object = 0) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return self._parse_percent(fallback)

    def _format_money(self, value: float) -> str:
        return f"${float(value or 0):,.2f}".rstrip("0").rstrip(".")

    def _format_quantity(self, value: float, symbol: str) -> str:
        base_asset = str(symbol or "").strip()
        if value >= 1000:
            return f"{value:,.0f} {base_asset}".strip()
        if value >= 1:
            return f"{value:,.2f} {base_asset}".strip()
        return f"{value:,.4f} {base_asset}".strip()


trade_decision_service = TradeDecisionService()

__all__ = [
    "TradeDecisionService",
    "trade_decision_service",
]
