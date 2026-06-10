"""Central registry for long-running worker thread status and logs."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import logging
from threading import Lock
from typing import Deque, Dict, List, Optional

from app.config.logging import build_worker_logger


MAX_WORKER_LOGS = 1000


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
    logs: Deque[WorkerLogEntry] = field(default_factory=deque)
    file_logger: Optional[logging.Logger] = None


class MonitorCenterService:
    def __init__(self) -> None:
        self._workers: Dict[str, WorkerState] = {}
        self._lock = Lock()

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
        with self._lock:
            state = self._workers.get(key)
            if state is None:
                state = WorkerState(
                    key=key,
                    name=name,
                    category=category,
                    thread_name=thread_name,
                    interval_seconds=interval_seconds,
                    status=status,
                    detail=detail,
                    file_logger=build_worker_logger(key),
                )
                self._workers[key] = state
                return

            state.name = name
            state.category = category
            state.thread_name = thread_name
            state.interval_seconds = interval_seconds
            state.status = status
            state.detail = detail
            if state.file_logger is None:
                state.file_logger = build_worker_logger(key)

    def heartbeat(self, key: str, *, status: str, detail: str) -> None:
        with self._lock:
            state = self._workers[key]
            state.status = status
            state.detail = detail
            state.last_heartbeat_at = datetime.now()

    def mark_success(self, key: str, message: str) -> None:
        with self._lock:
            state = self._workers[key]
            now = datetime.now()
            state.status = "running"
            state.detail = message
            state.last_heartbeat_at = now
            state.last_success_at = now
            self._append_log(state, WorkerLogEntry(time=now, level="INFO", message=message))

    def mark_error(self, key: str, message: str) -> None:
        with self._lock:
            state = self._workers[key]
            now = datetime.now()
            state.status = "error"
            state.detail = message
            state.last_heartbeat_at = now
            state.last_error_at = now
            state.last_error_message = message
            self._append_log(state, WorkerLogEntry(time=now, level="ERROR", message=message))

    def add_log(self, key: str, level: str, message: str) -> None:
        with self._lock:
            state = self._workers[key]
            self._append_log(
                state,
                WorkerLogEntry(time=datetime.now(), level=level.upper(), message=message),
            )

    def snapshot(self) -> List[dict]:
        with self._lock:
            result: List[dict] = []
            for state in self._workers.values():
                result.append(
                    {
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
                            for item in list(state.logs)[:MAX_WORKER_LOGS]
                        ],
                    }
                )
            return result

    def _append_log(self, state: WorkerState, entry: WorkerLogEntry) -> None:
        if state.file_logger is not None:
            state.file_logger.log(self._to_logging_level(entry.level), entry.message)
        if len(state.logs) >= MAX_WORKER_LOGS - 1:
            state.logs.clear()
            return
        state.logs.appendleft(entry)

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


monitor_center_service = MonitorCenterService()
