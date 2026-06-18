"""Snapshot service for cold-start recovery of opportunity pages."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.application.services.opportunity_exchange_filter_service import opportunity_exchange_filter_service
from app.infrastructure.cache import market_runtime_cache, strategy_runtime_cache
from app.infrastructure.persistence import opportunity_snapshot_repository


class OpportunitySnapshotService:
    def warm_public_runtime_cache_from_snapshot(self) -> Dict[str, bool]:
        funding_loaded = self._warm_public_channel_rows(channel="funding")
        spread_loaded = self._warm_public_channel_rows(channel="spread")
        return {
            "funding": funding_loaded,
            "spread": spread_loaded,
        }

    def warm_runtime_cache_from_snapshot(self, user_id: int) -> Dict[str, bool]:
        strategy_loaded = self._warm_strategy_payload(user_id=user_id)
        return {
            "funding": False,
            "spread": False,
            "strategy": strategy_loaded,
        }

    def persist_public_opportunity_rows(
        self,
        *,
        channel: str,
        rows: List[dict],
        generated_at: datetime | None = None,
    ) -> None:
        filtered_rows = opportunity_exchange_filter_service.filter_rows(rows)
        payload = {
            "rows": filtered_rows,
            "generated_at": (generated_at or datetime.now()).isoformat(),
        }
        opportunity_snapshot_repository.upsert_public_snapshot(
            channel=channel,
            payload=payload,
            row_count=len(filtered_rows),
            generated_at=generated_at or datetime.now(),
        )

    def persist_strategy_payload(self, *, user_id: int, payload: Dict[str, Any]) -> None:
        generated_at = payload.get("generated_at")
        if not isinstance(generated_at, datetime):
            generated_at = datetime.now()
        filtered_candidate_rows = opportunity_exchange_filter_service.filter_rows(
            list(payload.get("candidate_rows") or [])
        )
        snapshot_payload = {
            "summary_cards": list(payload.get("summary_cards") or []),
            "positions_rows": list(payload.get("positions_rows") or []),
            "order_rows": list(payload.get("order_rows") or []),
            "fill_rows": list(payload.get("fill_rows") or []),
            "candidate_rows": filtered_candidate_rows,
            "active_positions_rows": list(payload.get("active_positions_rows") or []),
            "active_order_rows": list(payload.get("active_order_rows") or []),
            "history_order_rows": list(payload.get("history_order_rows") or []),
            "generated_at": generated_at.isoformat(),
        }
        opportunity_snapshot_repository.upsert_snapshot(
            user_id=user_id,
            channel="strategy_runtime",
            payload=snapshot_payload,
            row_count=len(filtered_candidate_rows),
            generated_at=generated_at,
        )

    def _warm_public_channel_rows(self, *, channel: str) -> bool:
        if market_runtime_cache.get_public_rows_state(channel) is not None:
            return False

        snapshot = opportunity_snapshot_repository.get_public_snapshot(channel=channel)
        if snapshot is None:
            return False

        payload = snapshot.get("payload") or {}
        rows = payload.get("rows") or []
        filtered_rows = opportunity_exchange_filter_service.filter_rows(
            rows if isinstance(rows, list) else []
        )
        generated_at = self._parse_datetime(payload.get("generated_at")) or snapshot.get("generated_at")
        market_runtime_cache.set_public_rows(
            channel,
            filtered_rows,
            is_ready=False,
            source="snapshot",
            generated_at=generated_at,
            updated_at=snapshot.get("updated_at"),
            message="椤甸潰褰撳墠灞曠ず鏈€杩戜竴娆℃垚鍔熷揩鐓э紝瀹炴椂琛屾儏姝ｅ湪棰勭儹銆?",
        )
        return True

    def _warm_strategy_payload(self, *, user_id: int) -> bool:
        if strategy_runtime_cache.get_user_payload(user_id):
            return False

        snapshot = opportunity_snapshot_repository.get_snapshot(user_id=user_id, channel="strategy_runtime")
        if snapshot is None:
            return False

        payload = snapshot.get("payload") or {}
        filtered_candidate_rows = opportunity_exchange_filter_service.filter_rows(
            list(payload.get("candidate_rows") or [])
        )
        warmed_payload = {
            "summary_cards": list(payload.get("summary_cards") or []),
            "positions_rows": list(payload.get("positions_rows") or []),
            "order_rows": list(payload.get("order_rows") or []),
            "fill_rows": list(payload.get("fill_rows") or []),
            "candidate_rows": filtered_candidate_rows,
            "active_positions_rows": list(payload.get("active_positions_rows") or []),
            "active_order_rows": list(payload.get("active_order_rows") or []),
            "history_order_rows": list(payload.get("history_order_rows") or []),
            "generated_at": self._parse_datetime(payload.get("generated_at")) or snapshot.get("generated_at"),
            "is_ready": False,
            "source": "snapshot",
            "status_message": "椤甸潰褰撳墠灞曠ず鏈€杩戜竴娆℃垚鍔熷揩鐓э紝绛栫暐杩愯鎬佹鍦ㄩ鐑€?",
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

