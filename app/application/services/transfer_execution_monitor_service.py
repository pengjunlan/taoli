"""Background worker for executing transfer records."""

from __future__ import annotations

import logging
import threading
import time

from app.application.services.monitor_center_service import monitor_center_service
from app.application.services.account_support import MANUAL_TRANSFER_EXECUTION_MODE
from app.application.services.transfer_execution_service import transfer_execution_service
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import ExchangeError


logger = logging.getLogger(__name__)


# Current business behavior is intentionally preserved:
# worker-enabled manual transfer records are still executed by this background monitor.
WORKER_EXECUTION_SCOPE = MANUAL_TRANSFER_EXECUTION_MODE


class TransferExecutionMonitorService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._interval_seconds = 8
        self._batch_size = 10
        self._monitor_key = "transfer_execution_worker"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            monitor_center_service.register_worker(
                key=self._monitor_key,
                name="调拨执行线程",
                category="调拨执行",
                thread_name="transfer-execution-monitor",
                interval_seconds=self._interval_seconds,
                status="starting",
                detail="准备启动调拨执行线程",
            )
            self._thread = threading.Thread(
                target=self._run_loop,
                name="transfer-execution-monitor",
                daemon=True,
            )
            self._thread.start()

    def _run_loop(self) -> None:
        while True:
            try:
                monitor_center_service.heartbeat(
                    self._monitor_key,
                    status="running",
                    detail="线程心跳正常，准备扫描待执行调拨记录。",
                )
                handled_count = self._scan_pending_records()
                monitor_center_service.mark_success(
                    self._monitor_key,
                    f"本轮扫描完成，处理调拨记录 {handled_count} 条。",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Transfer execution monitor loop failed: %s", exc)
                monitor_center_service.mark_error(self._monitor_key, f"调拨执行线程异常: {exc}")
            time.sleep(self._interval_seconds)

    def _scan_pending_records(self) -> int:
        rows = account_repository.list_pending_worker_transfer_records(self._batch_size)
        handled_count = 0
        for row in rows:
            record_id = int(row["id"])
            if not account_repository.mark_transfer_record_processing(record_id):
                continue
            handled_count += 1
            self._execute_record(record_id)
        return handled_count

    def _execute_record(self, record_id: int) -> None:
        context = account_repository.get_transfer_record_execution_context(record_id)
        if context is None:
            account_repository.update_transfer_record_status(
                record_id,
                status="failed",
                result="调拨记录不存在，无法执行。",
            )
            return
        try:
            outcome = transfer_execution_service.execute(context)
            account_repository.update_transfer_record_status(
                record_id,
                status=outcome.status,
                result=outcome.result,
            )
            monitor_center_service.add_log(
                self._monitor_key,
                "info",
                f"调拨记录 #{record_id} 执行成功: {outcome.result}",
            )
        except ExchangeError as exc:
            account_repository.update_transfer_record_status(
                record_id,
                status="failed",
                result=str(exc),
            )
            monitor_center_service.add_log(
                self._monitor_key,
                "warning",
                f"调拨记录 #{record_id} 执行失败: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Transfer record execution failed: record_id=%s", record_id)
            account_repository.update_transfer_record_status(
                record_id,
                status="failed",
                result=f"后台执行异常: {exc}",
            )
            monitor_center_service.add_log(
                self._monitor_key,
                "error",
                f"调拨记录 #{record_id} 执行异常: {exc}",
            )


transfer_execution_monitor_service = TransferExecutionMonitorService()
