"""Market data monitoring service skeleton."""

from typing import List

from app.domain.entities.monitor_models import MarketOpportunity, ServiceHeartbeat


class MarketDataMonitorService:
    def heartbeat(self) -> ServiceHeartbeat:
        return ServiceHeartbeat(
            name="market_data_monitor",
            status="idle",
            detail="waiting for real market feeds and quote streams",
        )

    def collect_opportunities(self) -> List[MarketOpportunity]:
        return []
