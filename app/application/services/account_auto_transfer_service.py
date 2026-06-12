"""Auto transfer orchestration logic."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from app.application.services.account_support import AutoTransferConfigResult, AutoTransferExecutionResult
from app.application.services.account_transfer_capability_service import AccountTransferCapabilityService
from app.domain.entities import AuthUser
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import AccountPersistenceError, AccountValidationError


class AccountAutoTransferService:
    def __init__(self, query_service, transfer_planning_service) -> None:
        self._query_service = query_service
        self._transfer_planning_service = transfer_planning_service
        self._transfer_capability_service = AccountTransferCapabilityService()

    def get_auto_transfer_config(self, user_id: int) -> AutoTransferConfigResult:
        return self._query_service.get_auto_transfer_config(user_id)

    def update_auto_transfer_config(
        self,
        current_user: AuthUser,
        *,
        is_enabled: bool,
        trigger_ratio: float,
    ) -> AutoTransferConfigResult:
        if trigger_ratio <= 0 or trigger_ratio > 1:
            raise AccountValidationError("自动调拨触发比例必须大于 0 且不超过 1。")

        try:
            config = account_repository.upsert_auto_transfer_config(
                user_id=current_user.id,
                is_enabled=is_enabled,
                trigger_ratio=round(trigger_ratio, 4),
            )
        except Exception as exc:
            raise AccountPersistenceError("保存自动调拨配置失败：数据库操作异常。") from exc

        return AutoTransferConfigResult(
            is_enabled=bool(config.is_enabled),
            trigger_ratio=float(config.trigger_ratio),
        )

    def execute_auto_transfer(self, current_user: AuthUser) -> AutoTransferExecutionResult:
        config = self.get_auto_transfer_config(current_user.id)
        if not config.is_enabled:
            raise AccountValidationError("请先开启自动调拨。")

        pending_transfer = account_repository.get_open_worker_transfer_record_by_user_id(current_user.id)
        if pending_transfer is not None:
            record_id = int(pending_transfer["id"])
            status = str(pending_transfer.get("status") or "created")
            raise AccountValidationError(
                f"当前已有未完成的调拨记录 #{record_id}（状态：{status}），等待执行完成后再生成新的自动调拨。"
            )

        account_rows = self._query_service.build_account_rows_for_user(current_user.id)
        balance_rows = self._query_service.build_balance_rows_from_accounts(account_rows, config.trigger_ratio)
        candidate = self._pick_supported_auto_transfer_candidate(current_user.id, balance_rows, config.trigger_ratio)
        if candidate is None:
            raise AccountValidationError("当前没有同时满足自动调拨条件且支持真实执行的账户组合。")

        try:
            transfer_record = account_repository.create_transfer_record(
                user_id=current_user.id,
                from_account_id=int(candidate["from_account_id"]),
                to_account_id=int(candidate["to_account_id"]),
                amount=round(float(candidate["amount"]), 2),
                reason="自动真实调拨",
                status="created",
                is_worker_enabled=True,
                result=(
                    f"自动调拨任务已创建，后台将按真实执行链路处理；"
                    f"触发比例 {int(config.trigger_ratio * 100)}%，"
                    f"本次计划调拨 {self._query_service._format_currency(float(candidate['amount']))}。"
                ),
            )
        except Exception as exc:
            raise AccountPersistenceError("生成自动调拨记录失败：数据库操作异常。") from exc

        return AutoTransferExecutionResult(transfer_record=transfer_record)

    def maybe_execute_auto_transfer(self, user_id: int) -> Optional[AutoTransferExecutionResult]:
        config = self.get_auto_transfer_config(user_id)
        if not config.is_enabled:
            return None

        now = datetime.now()
        system_user = AuthUser(
            id=user_id,
            username="system",
            password_hash="",
            is_active=True,
            is_admin=True,
            created_at=now,
            updated_at=now,
        )
        try:
            return self.execute_auto_transfer(system_user)
        except AccountValidationError:
            return None

    def _pick_supported_auto_transfer_candidate(
        self,
        user_id: int,
        balance_rows,
        trigger_ratio: float,
    ) -> Optional[Dict[str, float | int | str]]:
        candidates = self._transfer_planning_service.list_auto_transfer_candidates(balance_rows, trigger_ratio)
        if not candidates:
            return None

        account_rows = account_repository.list_accounts_with_address_by_user_id(user_id)
        account_map = {int(row["id"]): row for row in account_rows}

        for candidate in candidates:
            from_account = account_map.get(int(candidate["from_account_id"]))
            to_account = account_map.get(int(candidate["to_account_id"]))
            if from_account is None or to_account is None:
                continue

            capability = self._transfer_capability_service.build_transfer_capability(from_account, to_account)
            if not capability["supported"]:
                continue

            return {
                **candidate,
                "mode": str(capability["mode"] or ""),
            }

        return None
