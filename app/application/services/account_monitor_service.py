"""Account monitoring service skeleton."""

from typing import List

from app.domain.entities.monitor_models import AccountSnapshot, ServiceHeartbeat


class AccountMonitorService:
    def heartbeat(self) -> ServiceHeartbeat:
        return ServiceHeartbeat(
            name="account_monitor",
            status="idle",
            detail="waiting for real exchange account connections",
        )

    def collect_account_snapshots(self) -> List[AccountSnapshot]:
        return []
