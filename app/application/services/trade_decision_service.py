"""Trade decision service skeleton."""

from typing import List

from app.domain.entities.monitor_models import MarketOpportunity, ServiceHeartbeat, TradeDecision


class TradeDecisionService:
    def heartbeat(self) -> ServiceHeartbeat:
        return ServiceHeartbeat(
            name="trade_decision",
            status="idle",
            detail="waiting for monitored account and market data",
        )

    def build_trade_decisions(
        self,
        opportunities: List[MarketOpportunity],
    ) -> List[TradeDecision]:
        decisions: List[TradeDecision] = []
        for opportunity in opportunities:
            action = "hold"
            should_execute = False
            if opportunity.open_signal:
                action = "open"
                should_execute = True
            elif opportunity.close_signal:
                action = "close"
                should_execute = True

            decisions.append(
                TradeDecision(
                    symbol=opportunity.symbol,
                    action=action,
                    reason="prototype decision pipeline",
                    should_execute=should_execute,
                )
            )
        return decisions
