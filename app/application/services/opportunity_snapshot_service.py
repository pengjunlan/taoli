"""Snapshot service for cold-start recovery of opportunity pages."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.infrastructure.cache import market_runtime_cache, strategy_runtime_cache
from app.infrastructure.persistence import opportunity_snapshot_repository


class OpportunitySnapshotService:
    def warm_runtime_cache_from_snapshot(self, user_id: int) -> Dict[str, bool]:
        funding_loaded = self._warm_channel_rows(user_id=user_id, channel="funding")
        spread_loaded = self._warm_channel_rows(user_id=user_id, channel="spread")
        strategy_loaded = self._warm_strategy_payload(user_id=user_id)
        return {
            "funding": funding_loaded,
            "spread": spread_loaded,
            "strategy": strategy_loaded,
        }

    def persist_opportunity_rows(
        self,
        *,
        user_id: int,
        channel: str,
        rows: List[dict],
        generated_at: datetime | None = None,
    ) -> None:
        payload = {
            "rows": list(rows),
            "generated_at": (generated_at or datetime.now()).isoformat(),
        }
        opportunity_snapshot_repository.upsert_snapshot(
            user_id=user_id,
            channel=channel,
            payload=payload,
            row_count=len(rows),
            generated_at=generated_at or datetime.now(),
        )

    def persist_strategy_payload(self, *, user_id: int, payload: Dict[str, Any]) -> None:
        generated_at = payload.get("generated_at")
        if not isinstance(generated_at, datetime):
            generated_at = datetime.now()
        snapshot_payload = {
            "summary_cards": list(payload.get("summary_cards") or []),
            "positions_rows": list(payload.get("positions_rows") or []),
            "order_rows": list(payload.get("order_rows") or []),
            "fill_rows": list(payload.get("fill_rows") or []),
            "candidate_rows": list(payload.get("candidate_rows") or []),
            "generated_at": generated_at.isoformat(),
        }
        row_count = len(snapshot_payload["candidate_rows"])
        opportunity_snapshot_repository.upsert_snapshot(
            user_id=user_id,
            channel="strategy_runtime",
            payload=snapshot_payload,
            row_count=row_count,
            generated_at=generated_at,
        )

    def _warm_channel_rows(self, *, user_id: int, channel: str) -> bool:
        if market_runtime_cache.get_user_rows_state(channel, user_id) is not None:
            return False

        snapshot = opportunity_snapshot_repository.get_snapshot(user_id=user_id, channel=channel)
        if snapshot is None:
            return False

        payload = snapshot.get("payload") or {}
        rows = payload.get("rows") or []
        generated_at = self._parse_datetime(payload.get("generated_at")) or snapshot.get("generated_at")
        market_runtime_cache.set_user_rows(
            channel,
            user_id,
            rows if isinstance(rows, list) else [],
            is_ready=False,
            source="snapshot",
            generated_at=generated_at,
            updated_at=snapshot.get("updated_at"),
            message="页面当前展示最近一次成功快照，实时行情正在预热。",
        )
        return True

    def _warm_strategy_payload(self, *, user_id: int) -> bool:
        if strategy_runtime_cache.get_user_payload(user_id):
            return False

        snapshot = opportunity_snapshot_repository.get_snapshot(user_id=user_id, channel="strategy_runtime")
        if snapshot is None:
            return False

        payload = snapshot.get("payload") or {}
        warmed_payload = {
            "summary_cards": list(payload.get("summary_cards") or []),
            "positions_rows": list(payload.get("positions_rows") or []),
            "order_rows": list(payload.get("order_rows") or []),
            "fill_rows": list(payload.get("fill_rows") or []),
            "candidate_rows": list(payload.get("candidate_rows") or []),
            "generated_at": self._parse_datetime(payload.get("generated_at")) or snapshot.get("generated_at"),
            "is_ready": False,
            "source": "snapshot",
            "status_message": "页面当前展示最近一次成功快照，策略运行态正在预热。",
            "updated_at": snapshot.get("updated_at"),
        }
        strategy_runtime_cache.set_user_payload(user_id, warmed_payload)
        return True

    def _parse_datetime(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None


opportunity_snapshot_service = OpportunitySnapshotService()

