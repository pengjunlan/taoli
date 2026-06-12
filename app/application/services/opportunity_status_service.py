"""Read-side status service for opportunity pages and cold-start diagnostics."""

from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Any, Dict

from app.application.services.local_position_service import local_position_service
from app.application.services.monitor_center_service import monitor_center_service
from app.infrastructure.cache import market_runtime_cache, strategy_runtime_cache
from app.infrastructure.persistence import opportunity_snapshot_repository
from app.infrastructure.persistence.market_repository import market_repository


class OpportunityStatusService:
    def build_channel_payload(
        self,
        *,
        channel: str,
        user_id: int,
        page: int = 1,
        page_size: int = 5,
    ) -> Dict[str, object]:
        state = market_runtime_cache.get_user_rows_state(channel, user_id)
        rows = list(state.rows) if state is not None else []
        total_rows = len(rows)
        safe_page_size = max(1, int(page_size or 5))
        total_pages = max(1, ceil(total_rows / safe_page_size)) if total_rows else 1
        safe_page = min(max(1, int(page or 1)), total_pages)
        start_index = (safe_page - 1) * safe_page_size
        end_index = start_index + safe_page_size
        page_rows = rows[start_index:end_index]
        page_rows = local_position_service.enrich_opportunity_rows(rows=page_rows)
        status = self._resolve_channel_status(channel=channel, state=state)
        diagnostics = self._build_channel_diagnostics(channel=channel, user_id=user_id, state=state)

        return {
            "channel": channel,
            "rows": page_rows,
            "opportunity_count": total_rows,
            "page": safe_page,
            "page_size": safe_page_size,
            "page_count": total_pages,
            "runtime_status": status,
            "diagnostics": diagnostics,
        }

    def build_strategy_payload(self, *, user_id: int) -> Dict[str, object]:
        payload = strategy_runtime_cache.get_user_payload(user_id)
        if not payload:
            return {
                "summary_cards": [],
                "positions_rows": [],
                "order_rows": [],
                "fill_rows": [],
                "candidate_rows": [],
                "generated_at": "--",
                "runtime_status": {
                    "state": "initializing",
                    "label": "预热中",
                    "tone": "warning",
                    "message": "策略运行态尚未生成，正在等待机会链路完成预热。",
                    "generated_at": "--",
                    "updated_at": "--",
                    "source": "none",
                    "is_ready": False,
                },
            }

        generated_at = payload.get("generated_at")
        updated_at = payload.get("updated_at")
        is_ready = bool(payload.get("is_ready", True))
        source = str(payload.get("source") or "runtime")
        status_message = str(payload.get("status_message") or "").strip()

        runtime_status = {
            "state": "ready" if is_ready else "stale",
            "label": "实时中" if is_ready else "快照中",
            "tone": "positive" if is_ready else "warning",
            "message": status_message or ("策略运行态已更新。" if is_ready else "正在展示最近一次成功快照。"),
            "generated_at": self._format_datetime(generated_at),
            "updated_at": self._format_datetime(updated_at),
            "source": source,
            "is_ready": is_ready,
        }

        return {
            "summary_cards": list(payload.get("summary_cards") or []),
            "positions_rows": list(payload.get("positions_rows") or []),
            "order_rows": list(payload.get("order_rows") or []),
            "fill_rows": list(payload.get("fill_rows") or []),
            "candidate_rows": list(payload.get("candidate_rows") or []),
            "generated_at": self._format_datetime(generated_at),
            "runtime_status": runtime_status,
        }

    def build_runtime_overview(self) -> Dict[str, object]:
        workers = monitor_center_service.snapshot()
        snapshot_counts = opportunity_snapshot_repository.list_snapshot_counts()
        active_pairs = market_repository.list_active_pairs()
        funding_pairs = sum(1 for row in active_pairs if str(row.get("pair_type") or "") == "funding")
        spread_pairs = sum(1 for row in active_pairs if str(row.get("pair_type") or "") == "spread")

        return {
            "workers": workers,
            "snapshot_counts": [
                {
                    "channel": str(row.get("channel") or ""),
                    "snapshot_count": int(row.get("snapshot_count") or 0),
                    "total_rows": int(row.get("total_rows") or 0),
                    "latest_generated_at": self._format_datetime(row.get("latest_generated_at")),
                }
                for row in snapshot_counts
            ],
            "pair_summary": {
                "funding_pairs": funding_pairs,
                "spread_pairs": spread_pairs,
                "pair_count": len(active_pairs),
            },
        }

    def _resolve_channel_status(self, *, channel: str, state) -> Dict[str, object]:
        if state is None:
            return {
                "state": "initializing",
                "label": "预热中",
                "tone": "warning",
                "message": f"{channel} 机会尚未生成，正在等待市场目录、配对和实时行情预热。",
                "generated_at": "--",
                "updated_at": "--",
                "source": "none",
                "is_ready": False,
            }

        if state.is_ready:
            return {
                "state": "ready",
                "label": "实时中",
                "tone": "positive",
                "message": state.message or "当前展示的是实时计算结果。",
                "generated_at": self._format_datetime(state.generated_at),
                "updated_at": self._format_datetime(state.updated_at),
                "source": state.source,
                "is_ready": True,
            }

        return {
            "state": "stale",
            "label": "快照中",
            "tone": "warning",
            "message": state.message or "当前展示最近一次成功快照，实时行情仍在预热。",
            "generated_at": self._format_datetime(state.generated_at),
            "updated_at": self._format_datetime(state.updated_at),
            "source": state.source,
            "is_ready": False,
        }

    def _build_channel_diagnostics(self, *, channel: str, user_id: int, state) -> Dict[str, object]:
        snapshot = opportunity_snapshot_repository.get_snapshot(user_id=user_id, channel=channel)
        active_pairs = market_repository.list_active_pairs(pair_type=channel)
        return {
            "active_pair_count": len(active_pairs),
            "snapshot_exists": snapshot is not None,
            "snapshot_generated_at": self._format_datetime(snapshot.get("generated_at") if snapshot else None),
            "runtime_row_count": len(state.rows) if state is not None else 0,
        }

    def _format_datetime(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return "--"


opportunity_status_service = OpportunityStatusService()
