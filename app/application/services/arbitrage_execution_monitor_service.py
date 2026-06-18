"""Background worker for arbitrage order leg execution."""

from __future__ import annotations

import logging
import threading
import time

from app.application.services.arbitrage_execution_service import arbitrage_execution_service
from app.application.services.monitor_center_service import monitor_center_service
from app.infrastructure.persistence import arbitrage_execution_repository


logger = logging.getLogger(__name__)


class ArbitrageExecutionMonitorService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._interval_seconds = 2
        self._batch_size = 30
        self._monitor_key = "arbitrage_execution_monitor"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            monitor_center_service.register_worker(
                key=self._monitor_key,
                name="套利订单执行线程",
                category="套利执行",
                thread_name="arbitrage-execution-monitor",
                interval_seconds=self._interval_seconds,
                status="starting",
                detail="准备扫描待执行的套利订单腿",
            )
            self._thread = threading.Thread(
                target=self._run_loop,
                name="arbitrage-execution-monitor",
                daemon=True,
            )
            self._thread.start()

    def _run_loop(self) -> None:
        while True:
            try:
                monitor_center_service.heartbeat(
                    self._monitor_key,
                    status="running",
                    detail="线程心跳正常，准备处理套利订单腿",
                )
                handled_count = self._scan_pending_order_legs()
                monitor_center_service.mark_success(
                    self._monitor_key,
                    f"本轮已处理 {handled_count} 条套利订单腿",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Arbitrage execution monitor loop failed: %s", exc)
                monitor_center_service.mark_error(
                    self._monitor_key,
                    f"套利订单执行线程异常: {exc}",
                )
            time.sleep(self._interval_seconds)

    def _scan_pending_order_legs(self) -> int:
        rows = arbitrage_execution_repository.list_pending_order_legs(limit=self._batch_size)
        handled_count = 0
        for row in rows:
            arbitrage_execution_service.process_order_leg(row)
            handled_count += 1
        return handled_count


arbitrage_execution_monitor_service = ArbitrageExecutionMonitorService()
