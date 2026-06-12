"""Read-side service for runtime strategy monitoring payloads."""

from __future__ import annotations

from typing import Dict, List

from app.application.services.opportunity_status_service import opportunity_status_service


class StrategyRuntimeService:
    def get_positions_orders_payload(self, user_id: int) -> Dict[str, object]:
        payload = opportunity_status_service.build_strategy_payload(user_id=user_id)
        if payload.get("summary_cards"):
            return payload
        return {
            **payload,
            "summary_cards": self._empty_summary_cards(),
        }

    def _empty_summary_cards(self) -> List[Dict[str, str]]:
        return [
            {
                "key": "candidate_count",
                "label": "规则命中候选",
                "value": "0",
                "change": "等待规则与机会数据进入运行链",
                "tone": "neutral",
            },
            {
                "key": "pending_orders",
                "label": "待执行记录",
                "value": "0",
                "change": "当前还没有候选执行项",
                "tone": "neutral",
            },
            {
                "key": "planned_amount",
                "label": "计划下单资金",
                "value": "$0",
                "change": "尚未生成策略候选金额",
                "tone": "neutral",
            },
            {
                "key": "fill_count",
                "label": "真实成交回报",
                "value": "0",
                "change": "执行引擎未接交易所回报前保持为空",
                "tone": "neutral",
            },
        ]


strategy_runtime_service = StrategyRuntimeService()
