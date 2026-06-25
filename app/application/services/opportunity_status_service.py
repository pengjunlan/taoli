"""Read-side status service for opportunity pages and cold-start diagnostics."""

from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Any, Dict

from app.application.services.local_position_service import local_position_service
from app.application.services.monitor_center_service import monitor_center_service
from app.application.services.opportunity_exchange_filter_service import opportunity_exchange_filter_service
from app.application.services.strategy_open_candidate_service import strategy_open_candidate_service
from app.application.services.opportunity_user_overlay_service import opportunity_user_overlay_service
from app.infrastructure.cache import market_runtime_cache, strategy_runtime_cache
from app.infrastructure.persistence import opportunity_snapshot_repository
from app.infrastructure.persistence.market_repository import market_repository


class OpportunityStatusService:
    def build_live_channel_payload(
        self,
        *,
        channel: str,
        user_id: int,
        page: int = 1,
        page_size: int = 5,
        locked_keys: list[str] | None = None,
    ) -> Dict[str, object]:
        payload = self.build_channel_payload(
            channel=channel,
            user_id=user_id,
            page=page,
            page_size=page_size,
            locked_keys=locked_keys,
        )
        return {
            "channel": channel,
            "rows": list(payload.get("rows") or []),
            "opportunity_count": int(payload.get("opportunity_count") or 0),
            "page": int(payload.get("page") or 1),
            "page_size": int(payload.get("page_size") or 5),
            "page_count": int(payload.get("page_count") or 1),
            "runtime_status": payload.get("runtime_status"),
            "diagnostics": payload.get("diagnostics"),
        }

    def build_channel_payload(
        self,
        *,
        channel: str,
        user_id: int,
        page: int = 1,
        page_size: int = 5,
        locked_keys: list[str] | None = None,
    ) -> Dict[str, object]:
        state = market_runtime_cache.get_public_rows_state(channel)
        snapshot = None
        if state is None:
            snapshot = opportunity_snapshot_repository.get_public_snapshot(channel=channel)
            from app.application.services.opportunity_snapshot_service import opportunity_snapshot_service

            opportunity_snapshot_service.warm_public_runtime_cache_from_snapshot()
            state = market_runtime_cache.get_public_rows_state(channel)
        rows = opportunity_exchange_filter_service.filter_rows(state.rows if state is not None else [])
        if state is not None and not state.is_ready and not rows:
            snapshot = snapshot or opportunity_snapshot_repository.get_public_snapshot(channel=channel)
            rows = self._extract_snapshot_rows(snapshot)
        total_rows = len(rows)
        safe_page_size = max(1, int(page_size or 5))
        total_pages = max(1, ceil(total_rows / safe_page_size)) if total_rows else 1
        safe_page = min(max(1, int(page or 1)), total_pages)
        if locked_keys:
            page_rows = self._select_locked_rows(rows=rows, locked_keys=locked_keys)
        else:
            start_index = (safe_page - 1) * safe_page_size
            end_index = start_index + safe_page_size
            page_rows = rows[start_index:end_index]
        page_rows = opportunity_user_overlay_service.enrich_display_rows(
            user_id=user_id,
            channel=channel,
            rows=page_rows,
        )
        page_rows = strategy_open_candidate_service.enrich_rows(
            user_id=user_id,
            channel=channel,
            rows=page_rows,
        )
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
            from app.application.services.opportunity_snapshot_service import opportunity_snapshot_service

            opportunity_snapshot_service.warm_runtime_cache_from_snapshot(user_id)
            payload = strategy_runtime_cache.get_user_payload(user_id)
        if not payload:
            return {
                "summary_cards": [],
                "positions_rows": [],
                "order_rows": [],
                "fill_rows": [],
                "candidate_rows": [],
                "active_positions_rows": [],
                "active_order_rows": [],
                "history_order_rows": [],
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
        is_ready = bool(payload.get("is_ready", False))
        source = str(payload.get("source") or "runtime")
        status_message = str(payload.get("status_message") or "").strip()
        candidate_rows = opportunity_exchange_filter_service.filter_rows(
            list(payload.get("candidate_rows") or [])
        )

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
            "candidate_rows": candidate_rows,
            "active_positions_rows": list(payload.get("active_positions_rows") or []),
            "active_order_rows": list(payload.get("active_order_rows") or []),
            "history_order_rows": list(payload.get("history_order_rows") or []),
            "generated_at": self._format_datetime(generated_at),
            "runtime_status": runtime_status,
        }

    def build_runtime_overview(self) -> Dict[str, object]:
        workers = monitor_center_service.snapshot()
        snapshot_counts = opportunity_snapshot_repository.list_snapshot_counts()
        funding_pairs = market_repository.count_active_pairs(pair_type="funding")
        spread_pairs = market_repository.count_active_pairs(pair_type="spread")

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
                "pair_count": funding_pairs + spread_pairs,
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
        _ = user_id
        snapshot = opportunity_snapshot_repository.get_public_snapshot(channel=channel)
        return {
            "active_pair_count": market_repository.count_active_pairs(pair_type=channel),
            "snapshot_exists": snapshot is not None,
            "snapshot_generated_at": self._format_datetime(snapshot.get("generated_at") if snapshot else None),
            "runtime_row_count": len(state.rows) if state is not None else 0,
        }

    def _extract_snapshot_rows(self, snapshot: Dict[str, Any] | None) -> list[dict]:
        if not snapshot:
            return []
        payload = snapshot.get("payload") or {}
        rows = payload.get("rows") or []
        if not isinstance(rows, list):
            return []
        return opportunity_exchange_filter_service.filter_rows(rows)

    def _select_locked_rows(self, *, rows: list[dict], locked_keys: list[str]) -> list[dict]:
        row_map = {
            self._row_key(row): row
            for row in rows
            if self._row_key(row)
        }
        result: list[dict] = []
        for locked_key in locked_keys:
            normalized_key = str(locked_key or "").strip()
            if not normalized_key:
                continue
            row = row_map.get(normalized_key)
            if row is not None:
                result.append(row)
        return result

    def _row_key(self, row: Dict[str, Any]) -> str:
        market_pair_key = str(row.get("market_pair_key") or "").strip()
        if market_pair_key:
            return market_pair_key
        return ""

    def _format_datetime(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return "--"


opportunity_status_service = OpportunityStatusService()
