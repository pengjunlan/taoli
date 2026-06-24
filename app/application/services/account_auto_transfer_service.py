"""Auto transfer orchestration logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from app.application.services.auto_transfer_account_guard_service import auto_transfer_account_guard_service
from app.application.services.account_monitor_service import account_monitor_service
from app.application.services.account_support import (
    AutoTransferConfigResult,
    AutoTransferExecutionResult,
    build_transfer_config_fingerprint,
    build_transfer_execution_payload,
    build_transfer_execution_snapshot,
)
from app.application.services.account_transfer_capability_service import AccountTransferCapabilityService
from app.domain.entities import AuthUser
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import AccountNotFoundError, AccountPersistenceError, AccountValidationError


AUTO_REAL_TRANSFER_REASON = "自动真实调拨"


@dataclass(frozen=True)
class AutoTransferAccountSnapshot:
    account_id: int
    user_id: int
    account_name: str
    exchange_code: str
    market_type: str
    api_key: str
    api_secret: str
    api_passphrase: str
    current_available_amount: float
    current_total_amount: float
    funding_ratio_percent: float
    connection_test_status: str
    is_active: bool
    network: str
    address_value: str
    memo_tag: str


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

        account_rows = account_repository.list_active_accounts_with_address_by_user_id(current_user.id)
        account_snapshots = self._build_account_snapshots(account_rows)
        candidate = self._pick_auto_transfer_candidate(current_user.id, account_snapshots, config.trigger_ratio)
        if candidate is None:
            raise AccountValidationError("当前没有同时满足自动调拨条件的账户组合。")

        self._ensure_no_open_transfer_conflicts(
            current_user.id,
            from_account_id=int(candidate["from_account_id"]),
            to_account_id=int(candidate["to_account_id"]),
        )

        pending_transfer = account_repository.get_open_worker_transfer_record_by_target_account_id(
            int(candidate["to_account_id"])
        )
        if pending_transfer is not None:
            record_id = int(pending_transfer["id"])
            status = str(
                pending_transfer.get("execute_status")
                or pending_transfer.get("status")
                or "pending_execute"
            )
            raise AccountValidationError(
                f"当前目标账户已有未完成的调拨记录 #{record_id}（状态：{status}），请等待执行完成后再继续自动调拨。"
            )

        execution_snapshot = build_transfer_execution_snapshot(
            self._snapshot_to_account_row(
                next(snapshot for snapshot in account_snapshots if snapshot.account_id == int(candidate["from_account_id"]))
            ),
            self._snapshot_to_account_row(
                next(snapshot for snapshot in account_snapshots if snapshot.account_id == int(candidate["to_account_id"]))
            ),
        )
        config_fingerprint = build_transfer_config_fingerprint(execution_snapshot)
        execution_payload = build_transfer_execution_payload(execution_snapshot)

        try:
            transfer_record = account_repository.create_transfer_record(
                user_id=current_user.id,
                from_account_id=int(candidate["from_account_id"]),
                to_account_id=int(candidate["to_account_id"]),
                amount=round(float(candidate["amount"]), 2),
                reason=AUTO_REAL_TRANSFER_REASON,
                status="pending",
                execute_status="pending_execute",
                result_status="none",
                config_fingerprint=config_fingerprint,
                is_worker_enabled=True,
                execution_payload=execution_payload,
                result=(
                    "自动调拨任务已创建，后台将按真实执行链路处理。"
                    f" 本次计划调拨 {self._query_service._format_currency(float(candidate['amount']))}。"
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

    def _pick_auto_transfer_candidate(
        self,
        user_id: int,
        account_snapshots: List[AutoTransferAccountSnapshot],
        trigger_ratio: float,
    ) -> Optional[Dict[str, float | int | str]]:
        balance_rows = self._build_balance_rows(account_snapshots, trigger_ratio)
        candidates = self._transfer_planning_service.list_auto_transfer_candidates(balance_rows, trigger_ratio)
        if not candidates:
            return None

        account_map = {snapshot.account_id: snapshot for snapshot in account_snapshots}

        for candidate in candidates:
            from_account = account_map.get(int(candidate["from_account_id"]))
            to_account = account_map.get(int(candidate["to_account_id"]))
            if from_account is None or to_account is None:
                continue
            if auto_transfer_account_guard_service.is_frozen(user_id, int(candidate["from_account_id"])):
                continue
            if auto_transfer_account_guard_service.is_frozen(user_id, int(candidate["to_account_id"])):
                continue
            if not from_account.is_active or not to_account.is_active:
                continue
            if from_account.connection_test_status != "success":
                continue
            if to_account.connection_test_status != "success":
                continue

            capability = self._transfer_capability_service.build_transfer_capability(
                self._snapshot_to_account_row(from_account),
                self._snapshot_to_account_row(to_account),
            )
            enriched_candidate = {
                **candidate,
                "mode": str(capability.get("mode") or ""),
                "route_supported": bool(capability.get("supported")),
                "route_block_reason": str(capability.get("reason") or ""),
            }

            if capability["supported"]:
                return enriched_candidate
        return None

    def unlock_auto_transfer_account(self, user_id: int, account_id: int) -> None:
        account = account_repository.get_account_with_address_by_id(account_id, user_id)
        if account is None:
            raise AccountNotFoundError("账户不存在，或你无权解冻该账户。")
        auto_transfer_account_guard_service.unlock_account(user_id, account_id)

    def _ensure_no_open_transfer_conflicts(
        self,
        user_id: int,
        *,
        from_account_id: int,
        to_account_id: int,
    ) -> None:
        conflict_checks = (
            (
                account_repository.get_open_worker_transfer_record_by_route(
                    user_id=user_id,
                    from_account_id=from_account_id,
                    to_account_id=to_account_id,
                ),
                "当前这条调拨路线已有未完成的调拨记录",
            ),
            (
                account_repository.get_open_worker_transfer_record_by_source_account_id(from_account_id),
                "当前转出账户已有未完成的调拨记录",
            ),
            (
                account_repository.get_open_worker_transfer_record_by_target_account_id(to_account_id),
                "当前转入账户已有未完成的调拨记录",
            ),
        )

        for pending_transfer, prefix in conflict_checks:
            if pending_transfer is None:
                continue
            record_id = int(pending_transfer["id"])
            status = str(
                pending_transfer.get("execute_status")
                or pending_transfer.get("status")
                or "pending_execute"
            )
            raise AccountValidationError(
                f"{prefix} #{record_id}（状态：{status}），请等待处理完成后再继续自动调拨。"
            )

    def _build_account_snapshots(self, rows: List[Dict[str, object]]) -> List[AutoTransferAccountSnapshot]:
        result: List[AutoTransferAccountSnapshot] = []
        for row in rows:
            account_id = int(row.get("id") or 0)
            user_id = int(row.get("user_id") or 0)
            cached_balance = account_monitor_service.get_cached_balance(account_id, user_id=user_id)
            available_amount = (
                float(cached_balance.amount)
                if cached_balance is not None
                else float(row.get("current_available_amount") or 0)
            )
            total_amount = (
                max(
                    float(cached_balance.total_amount or 0),
                    float(cached_balance.amount or 0) + float(cached_balance.frozen_amount or 0),
                    float(cached_balance.amount or 0),
                )
                if cached_balance is not None
                else float(row.get("current_available_amount") or 0)
            )
            result.append(
                AutoTransferAccountSnapshot(
                    account_id=account_id,
                    user_id=user_id,
                    account_name=str(row.get("account_name") or "--"),
                    exchange_code=str(row.get("exchange_code") or "").strip().lower(),
                    market_type=str(row.get("market_type") or "").strip().lower(),
                    api_key=str(row.get("api_key") or ""),
                    api_secret=str(row.get("api_secret") or ""),
                    api_passphrase=str(row.get("api_passphrase") or ""),
                    current_available_amount=max(available_amount, 0.0),
                    current_total_amount=max(total_amount, 0.0),
                    funding_ratio_percent=float(row.get("funding_ratio_percent") or 0),
                    connection_test_status=str(row.get("connection_test_status") or "").strip().lower(),
                    is_active=bool(row.get("is_active")),
                    network=str(row.get("network") or ""),
                    address_value=str(row.get("address_value") or ""),
                    memo_tag=str(row.get("memo_tag") or ""),
                )
            )
        return result

    def _build_balance_rows(
        self,
        snapshots: List[AutoTransferAccountSnapshot],
        trigger_ratio: float,
    ) -> List[Dict[str, str]]:
        total_available_value = sum(max(snapshot.current_available_amount, 0.0) for snapshot in snapshots)
        total_target_pool_value = total_available_value
        result: List[Dict[str, str]] = []

        for snapshot in snapshots:
            available_value = max(float(snapshot.current_available_amount or 0), 0.0)
            current_total_amount_value = max(float(snapshot.current_total_amount or 0), available_value)
            funding_ratio_percent = float(snapshot.funding_ratio_percent or 0)
            if funding_ratio_percent > 0:
                ratio = funding_ratio_percent / 100
            else:
                ratio = (available_value / total_available_value) if total_available_value > 0 else 0.0
            target_value = total_target_pool_value * ratio
            auto_trigger_value = target_value * trigger_ratio
            result.append(
                {
                    "id": str(snapshot.account_id),
                    "name": snapshot.account_name or "--",
                    "available": self._query_service._format_currency(available_value),
                    "current_balance": self._query_service._format_currency(current_total_amount_value),
                    "target": self._query_service._format_currency(target_value),
                    "auto_trigger_value": self._query_service._format_currency(auto_trigger_value),
                }
            )

        return result

    def _snapshot_to_account_row(self, snapshot: AutoTransferAccountSnapshot) -> Dict[str, object]:
        return {
            "id": snapshot.account_id,
            "user_id": snapshot.user_id,
            "exchange_code": snapshot.exchange_code,
            "market_type": snapshot.market_type,
            "api_key": snapshot.api_key,
            "api_secret": snapshot.api_secret,
            "api_passphrase": snapshot.api_passphrase,
            "network": snapshot.network,
            "address_value": snapshot.address_value,
            "memo_tag": snapshot.memo_tag,
        }
