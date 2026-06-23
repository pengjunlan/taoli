"""Background worker for executing transfer records."""

from __future__ import annotations

import logging
import threading
import time

from app.application.services.account_monitor_service import account_monitor_service
from app.application.services.account_support import MANUAL_TRANSFER_EXECUTION_MODE
from app.application.services.auto_transfer_account_guard_service import auto_transfer_account_guard_service
from app.application.services.monitor_center_service import monitor_center_service
from app.application.services.transfer_execution_service import transfer_execution_service
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import ExchangeError


logger = logging.getLogger(__name__)


WORKER_EXECUTION_SCOPE = MANUAL_TRANSFER_EXECUTION_MODE
AUTO_REAL_TRANSFER_REASON = "自动真实调拨"


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
            allow_recovering_executing = str(row.get("execute_status") or "").strip() == "executing"
            if not account_repository.mark_transfer_record_processing(
                record_id,
                allow_recovering_executing=allow_recovering_executing,
            ):
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
                execute_status="processed",
                result_status="failed",
                failure_type="business",
                failure_reason="调拨记录不存在，无法执行。",
            )
            return

        try:
            outcome = transfer_execution_service.execute(context)
            self._persist_resolved_destination(record_id, context)
            if str(context.get("reason") or "").strip() == AUTO_REAL_TRANSFER_REASON:
                auto_transfer_account_guard_service.clear_accounts(
                    int(context.get("user_id") or 0),
                    [
                        int(context.get("from_account_id") or 0),
                        int(context.get("to_account_id") or 0),
                    ],
                )
            account_repository.update_transfer_record_status(
                record_id,
                status=outcome.status,
                result=outcome.result,
                execute_status=outcome.execute_status,
                result_status=outcome.result_status,
                failure_type=outcome.failure_type,
                failure_reason=outcome.failure_reason,
                execution_checkpoint=outcome.execution_checkpoint,
                execution_reference=outcome.execution_reference,
                execution_payload=outcome.execution_payload,
            )
            self._refresh_involved_accounts(context)
            monitor_center_service.add_log(
                self._monitor_key,
                "info" if outcome.result_status == "success" else "warning",
                f"调拨记录 #{record_id} 执行结果: {outcome.result}",
            )
        except ExchangeError as exc:
            self._persist_resolved_destination(record_id, context)
            failure_type = "config" if transfer_execution_service.is_user_account_failure(exc) else "temporary"
            account_repository.update_transfer_record_status(
                record_id,
                status="failed",
                result=str(exc),
                execute_status="processed",
                result_status="failed",
                failure_type=failure_type,
                failure_reason=str(exc),
            )
            self._refresh_involved_accounts(context)
            if str(context.get("reason") or "").strip() == AUTO_REAL_TRANSFER_REASON:
                self._record_auto_transfer_account_failure(context, exc)
            monitor_center_service.add_log(
                self._monitor_key,
                "warning",
                f"调拨记录 #{record_id} 执行失败: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Transfer record execution failed: record_id=%s", record_id)
            self._persist_resolved_destination(record_id, context)
            if str(context.get("reason") or "").strip() == AUTO_REAL_TRANSFER_REASON:
                self._record_auto_transfer_account_failure(context, exc)
            account_repository.update_transfer_record_status(
                record_id,
                status="failed",
                result=f"后台执行异常: {exc}",
                execute_status="processed",
                result_status="failed",
                failure_type="temporary",
                failure_reason=str(exc),
            )
            self._refresh_involved_accounts(context)
            monitor_center_service.add_log(
                self._monitor_key,
                "error",
                f"调拨记录 #{record_id} 执行异常: {exc}",
            )

    def _persist_resolved_destination(self, record_id: int, context) -> None:
        to_address_value = str(context.get("_resolved_to_address_value") or "").strip()
        if not to_address_value:
            return

        account_repository.update_transfer_record_actual_destination(
            record_id,
            to_network=str(context.get("_resolved_to_network") or "").strip(),
            to_address_value=to_address_value,
            to_memo_tag=str(context.get("_resolved_to_memo_tag") or "").strip(),
        )

    def _record_auto_transfer_account_failure(self, context, error: Exception) -> None:
        user_id = int(context.get("user_id") or 0)
        if user_id <= 0:
            return

        failure = transfer_execution_service.classify_auto_transfer_failure(context, error)
        if not failure["freeze_worthy"] or int(failure["account_id"] or 0) <= 0:
            return

        auto_transfer_account_guard_service.record_failure(
            user_id=user_id,
            account_id=int(failure["account_id"]),
            exchange_code=str(failure["exchange_code"] or ""),
            account_name=str(failure["account_name"] or ""),
            error_category=str(failure["category"] or ""),
            error_label=str(failure["label"] or ""),
            raw_message=str(failure["raw_message"] or ""),
        )

    def _refresh_involved_accounts(self, context) -> None:
        account_ids = sorted(
            {
                int(context.get("from_account_id") or 0),
                int(context.get("to_account_id") or 0),
            }
        )
        account_ids = [account_id for account_id in account_ids if account_id > 0]
        if not account_ids:
            return
        try:
            account_monitor_service.refresh_accounts_by_ids(account_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Refresh involved accounts failed after transfer execution: %s", exc)


transfer_execution_monitor_service = TransferExecutionMonitorService()
