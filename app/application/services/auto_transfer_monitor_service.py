"""Background auto transfer monitor."""

from __future__ import annotations

import logging
import threading
import time

from app.application.services.account_service import account_service
from app.application.services.monitor_center_service import monitor_center_service
from app.infrastructure.persistence.account_repository import account_repository


logger = logging.getLogger(__name__)


class AutoTransferMonitorService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._interval_seconds = 20
        self._monitor_key = "auto_transfer_guard"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            monitor_center_service.register_worker(
                key=self._monitor_key,
                name="自动调拨守护线程",
                category="调拨监控",
                thread_name="auto-transfer-monitor",
                interval_seconds=self._interval_seconds,
                status="starting",
                detail="准备启动自动调拨守护线程",
            )
            self._thread = threading.Thread(
                target=self._run_loop,
                name="auto-transfer-monitor",
                daemon=True,
            )
            self._thread.start()

    def _run_loop(self) -> None:
        while True:
            try:
                monitor_center_service.heartbeat(
                    self._monitor_key,
                    status="running",
                    detail="线程心跳正常，准备扫描自动调拨配置",
                )
                self._scan_configs()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Auto transfer monitor loop failed: %s", exc)
                monitor_center_service.mark_error(self._monitor_key, f"自动调拨守护线程异常: {exc}")
            time.sleep(self._interval_seconds)

    def _scan_configs(self) -> None:
        rows = account_repository.list_all_accounts_with_address()
        user_ids = sorted({int(row["user_id"]) for row in rows})
        enabled_user_ids = []
        executed_count = 0

        for user_id in user_ids:
            config = account_service.get_auto_transfer_config(user_id)
            if not config.is_enabled:
                continue

            enabled_user_ids.append(user_id)
            result = account_service.maybe_execute_auto_transfer(user_id)
            if result is not None:
                executed_count += 1
                monitor_center_service.add_log(
                    self._monitor_key,
                    "info",
                    f"用户 {user_id} 已生成自动调拨记录 #{result.transfer_record.id}",
                )

        monitor_center_service.mark_success(
            self._monitor_key,
            (
                f"本轮扫描完成：启用自动调拨 {len(enabled_user_ids)} 个用户，"
                f"生成调拨记录 {executed_count} 条"
            ),
        )
        if enabled_user_ids:
            monitor_center_service.add_log(
                self._monitor_key,
                "info",
                f"当前启用自动调拨的用户：{', '.join(str(item) for item in enabled_user_ids)}",
            )


auto_transfer_monitor_service = AutoTransferMonitorService()
