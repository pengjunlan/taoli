"""Central registry for long-running worker thread status and logs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Dict, List, Optional

from app.config.logging import build_worker_logger
from app.infrastructure.cache import redis_runtime_support


MAX_WORKER_LOGS = 1000
REDIS_MAX_WORKER_LOGS = 200
RUNTIME_CACHE_KEY_PREFIX = "monitor-center:worker:"
RUNTIME_CACHE_HASH_KEY = "monitor-center:workers"
RUNTIME_CACHE_MIN_TTL_SECONDS = 5 * 60
RUNTIME_CACHE_INTERVAL_MULTIPLIER = 10


@dataclass
class WorkerLogEntry:
    time: datetime
    level: str
    message: str


@dataclass
class WorkerState:
    key: str
    name: str
    category: str
    status: str = "idle"
    detail: str = ""
    thread_name: str = ""
    interval_seconds: int = 0
    last_heartbeat_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None
    last_error_message: str = ""
    logs: List[WorkerLogEntry] = field(default_factory=list)
    file_logger: Optional[logging.Logger] = None
    last_saved_at: Optional[datetime] = None
    last_logged_message: str = ""


class MonitorCenterService:
    _MIN_SAVE_INTERVAL_SECONDS = 2

    def register_worker(
        self,
        *,
        key: str,
        name: str,
        category: str,
        thread_name: str,
        interval_seconds: int,
        status: str = "idle",
        detail: str = "",
    ) -> None:
        state = self._load_state(key) or WorkerState(key=key, name=name, category=category)
        state.name = name
        state.category = category
        state.thread_name = thread_name
        state.interval_seconds = interval_seconds
        state.status = status
        state.detail = detail
        if state.file_logger is None:
            state.file_logger = build_worker_logger(key)
        self._save_state(state)

    def heartbeat(self, key: str, *, status: str, detail: str) -> None:
        state = self._require_state(key)
        state.status = status
        state.detail = detail
        state.last_heartbeat_at = datetime.now()
        self._save_state(state, force=False)

    def mark_success(self, key: str, message: str) -> None:
        state = self._require_state(key)
        now = datetime.now()
        state.status = "running"
        state.detail = message
        state.last_heartbeat_at = now
        state.last_success_at = now
        self._append_log(state, WorkerLogEntry(time=now, level="INFO", message=message))
        self._save_state(state)

    def mark_error(self, key: str, message: str) -> None:
        state = self._require_state(key)
        now = datetime.now()
        state.status = "error"
        state.detail = message
        state.last_heartbeat_at = now
        state.last_error_at = now
        state.last_error_message = message
        self._append_log(state, WorkerLogEntry(time=now, level="ERROR", message=message))
        self._save_state(state)

    def add_log(self, key: str, level: str, message: str) -> None:
        state = self._require_state(key)
        self._append_log(
            state,
            WorkerLogEntry(time=datetime.now(), level=level.upper(), message=message),
        )
        self._save_state(state)

    def add_logs(self, key: str, entries: List[dict]) -> None:
        if not entries:
            return
        state = self._require_state(key)
        now = datetime.now()
        for item in entries:
            if not isinstance(item, dict):
                continue
            message = str(item.get("message") or "").strip()
            if not message:
                continue
            level = str(item.get("level") or "INFO").upper()
            entry_time = self._parse_datetime(item.get("time")) or now
            self._append_log(
                state,
                WorkerLogEntry(time=entry_time, level=level, message=message),
            )
        self._save_state(state)

    def snapshot(self) -> List[dict]:
        merged: Dict[str, dict] = {}
        for item in self._load_runtime_snapshot():
            key = str(item.get("key") or "").strip()
            if key:
                merged[key] = item
        return sorted(
            merged.values(),
            key=lambda item: (
                str(item.get("category") or ""),
                str(item.get("name") or ""),
                str(item.get("key") or ""),
            ),
        )

    def _append_log(self, state: WorkerState, entry: WorkerLogEntry) -> None:
        if state.last_logged_message == entry.message and state.logs:
            state.logs[0] = entry
            return
        if state.file_logger is not None:
            state.file_logger.log(self._to_logging_level(entry.level), entry.message)
        state.logs.insert(0, entry)
        state.last_logged_message = entry.message
        if len(state.logs) > MAX_WORKER_LOGS:
            state.logs = state.logs[:MAX_WORKER_LOGS]

    def _serialize_state(self, state: WorkerState, *, log_limit: int) -> dict:
        return {
            "key": state.key,
            "name": state.name,
            "category": state.category,
            "status": state.status,
            "detail": state.detail,
            "thread_name": state.thread_name,
            "interval_seconds": state.interval_seconds,
            "last_heartbeat_at": self._format_datetime(state.last_heartbeat_at),
            "last_success_at": self._format_datetime(state.last_success_at),
            "last_error_at": self._format_datetime(state.last_error_at),
            "last_error_message": state.last_error_message,
            "logs": [
                {
                    "time": self._format_datetime(item.time),
                    "level": item.level,
                    "message": item.message,
                }
                for item in list(state.logs)[:log_limit]
            ],
        }

    def _save_state(self, state: WorkerState, *, force: bool = True) -> None:
        now = datetime.now()
        if not force and state.last_saved_at is not None:
            elapsed = (now - state.last_saved_at).total_seconds()
            if elapsed < self._MIN_SAVE_INTERVAL_SECONDS:
                return
        item = self._serialize_state(state, log_limit=REDIS_MAX_WORKER_LOGS)
        ttl_seconds = self._runtime_ttl_seconds(state.interval_seconds)
        redis_runtime_support.set_hash_field_json(
            RUNTIME_CACHE_HASH_KEY,
            state.key,
            item,
            ttl_seconds=ttl_seconds,
        )
        state.last_saved_at = now
        redis_runtime_support.set_json(self._runtime_key(state.key), item, ttl_seconds=ttl_seconds)

    def _runtime_ttl_seconds(self, interval_seconds: int) -> int:
        resolved_interval = max(1, int(interval_seconds or 0))
        return max(RUNTIME_CACHE_MIN_TTL_SECONDS, resolved_interval * RUNTIME_CACHE_INTERVAL_MULTIPLIER)

    def _load_runtime_snapshot(self) -> List[dict]:
        result: List[dict] = []
        payload_map = redis_runtime_support.get_hash_json(RUNTIME_CACHE_HASH_KEY)
        for _, item in payload_map.items():
            if isinstance(item, dict):
                result.append(item)
        if result:
            return result
        for _, item in redis_runtime_support.list_json(f"{RUNTIME_CACHE_KEY_PREFIX}*"):
            if isinstance(item, dict):
                result.append(item)
        return result

    def _load_state(self, key: str) -> WorkerState | None:
        payload = redis_runtime_support.get_hash_field_json(RUNTIME_CACHE_HASH_KEY, key)
        if not isinstance(payload, dict):
            payload = redis_runtime_support.get_json(self._runtime_key(key))
        if not isinstance(payload, dict):
            return None
        return self._deserialize_state(payload)

    def _require_state(self, key: str) -> WorkerState:
        state = self._load_state(key)
        if state is not None:
            if state.file_logger is None:
                state.file_logger = build_worker_logger(key)
            return state
        state = WorkerState(
            key=key,
            name=key,
            category="runtime",
            status="starting",
            detail="worker state was reconstructed from runtime cache",
            file_logger=build_worker_logger(key),
        )
        return state

    def _deserialize_state(self, payload: dict) -> WorkerState:
        logs: List[WorkerLogEntry] = []
        for item in list(payload.get("logs") or [])[:MAX_WORKER_LOGS]:
            if not isinstance(item, dict):
                continue
            logs.append(
                WorkerLogEntry(
                    time=self._parse_datetime(item.get("time")) or datetime.now(),
                    level=str(item.get("level") or "INFO").upper(),
                    message=str(item.get("message") or ""),
                )
            )
        return WorkerState(
            key=str(payload.get("key") or ""),
            name=str(payload.get("name") or ""),
            category=str(payload.get("category") or ""),
            status=str(payload.get("status") or "idle"),
            detail=str(payload.get("detail") or ""),
            thread_name=str(payload.get("thread_name") or ""),
            interval_seconds=int(payload.get("interval_seconds") or 0),
            last_heartbeat_at=self._parse_datetime(payload.get("last_heartbeat_at")),
            last_success_at=self._parse_datetime(payload.get("last_success_at")),
            last_error_at=self._parse_datetime(payload.get("last_error_at")),
            last_error_message=str(payload.get("last_error_message") or ""),
            logs=logs,
            file_logger=None,
            last_saved_at=None,
            last_logged_message=str(logs[0].message) if logs else "",
        )

    def _to_logging_level(self, level: str) -> int:
        normalized = str(level or "").upper()
        if normalized == "ERROR":
            return logging.ERROR
        if normalized == "WARNING":
            return logging.WARNING
        return logging.INFO

    def _format_datetime(self, value: Optional[datetime]) -> str:
        if value is None:
            return "--"
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def _parse_datetime(self, value: object) -> Optional[datetime]:
        text = str(value or "").strip()
        if not text or text == "--":
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            try:
                return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None

    def _runtime_key(self, key: str) -> str:
        return f"{RUNTIME_CACHE_KEY_PREFIX}{key}"


monitor_center_service = MonitorCenterService()
