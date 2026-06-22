"""Write-side account service logic."""

from __future__ import annotations

from datetime import datetime

from app.application.dto.requests import AccountCreateRequest, AccountTransferCreateRequest, AccountUpdateRequest
from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.auto_transfer_account_guard_service import auto_transfer_account_guard_service
from app.application.services.account_monitor_service import account_monitor_service
from app.application.services.account_support import (
    AccountCreateResult,
    AccountServiceSupport,
    MANUAL_TRANSFER_EXECUTION_MODE,
    MANUAL_TRANSFER_EXECUTION_RESULT_HINT,
    TransferCreateResult,
)
from app.application.services.account_transfer_capability_service import AccountTransferCapabilityService
from app.application.services.exchange_connection_service import exchange_connection_service
from app.domain.entities import AuthUser
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import (
    AccountNotFoundError,
    AccountPersistenceError,
    AccountValidationError,
    ExchangeError,
)


class AccountCommandService(AccountServiceSupport):
    CONNECTION_UPDATE_CLEARABLE_GUARD_CATEGORIES = {
        "permission_denied",
        "api_auth_failed",
        "ip_whitelist_blocked",
        "withdraw_disabled",
        "account_mapping_invalid",
    }
    ADDRESS_UPDATE_CLEARABLE_GUARD_CATEGORIES = {
        "address_invalid",
        "network_invalid",
        "deposit_info_invalid",
    }
    CONNECTION_TEST_SUCCESS_CLEARABLE_GUARD_CATEGORIES = {
        "permission_denied",
        "api_auth_failed",
        "ip_whitelist_blocked",
        "account_mapping_invalid",
    }

    def __init__(self) -> None:
        self._transfer_capability_service = AccountTransferCapabilityService()

    def create_account(self, payload: AccountCreateRequest, current_user: AuthUser) -> AccountCreateResult:
        normalized = self._normalize_payload(
            market_type=payload.market_type,
            exchange_code=payload.exchange_code,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            api_passphrase=payload.api_passphrase,
            connection_test_status=payload.connection_test_status,
            address_network=payload.address_network,
            address_value=payload.address_value,
            address_memo=payload.address_memo,
        )

        self._validate_account_payload(
            market_type=normalized["market_type"],
            exchange_code=normalized["exchange_code"],
            api_key=normalized["api_key"],
            api_secret=normalized["api_secret"],
            address_network=normalized["address_network"],
            address_value=normalized["address_value"],
        )

        account_name = self._build_account_name(normalized["exchange_code"], normalized["market_type"])

        try:
            account = account_repository.create_account(
                user_id=current_user.id,
                market_type=normalized["market_type"],
                exchange_code=normalized["exchange_code"],
                account_name=account_name,
                api_key=normalized["api_key"],
                api_secret=normalized["api_secret"],
                api_passphrase=normalized["api_passphrase"],
                connection_test_status=normalized["connection_test_status"] or "untested",
                funding_ratio_percent=0,
            )
            account_repository.upsert_address(
                account_id=account.id,
                network=normalized["address_network"],
                address_value=normalized["address_value"],
                memo_tag=normalized["address_memo"],
            )
            account_monitor_service.seed_account(
                account.id,
                0,
                None,
                user_id=current_user.id,
                exchange_code=normalized["exchange_code"],
                market_type=normalized["market_type"],
                frozen_amount=0,
                total_amount=0,
            )
        except Exception as exc:
            raise AccountPersistenceError("保存账户失败：写入数据库时出错。") from exc

        return AccountCreateResult(account=account)

    def update_account(
        self,
        account_id: int,
        payload: AccountUpdateRequest,
        current_user: AuthUser,
    ) -> AccountCreateResult:
        existing = account_repository.get_account_with_address_by_id(account_id, current_user.id)
        if existing is None:
            raise AccountNotFoundError("账户不存在，或你无权编辑该账户。")

        normalized = self._normalize_payload(
            market_type=payload.market_type,
            exchange_code=payload.exchange_code,
            api_key=payload.api_key,
            api_secret=payload.api_secret or str(existing["api_secret"]),
            api_passphrase=payload.api_passphrase,
            connection_test_status=payload.connection_test_status,
            address_network=payload.address_network,
            address_value=payload.address_value,
            address_memo=payload.address_memo,
        )

        self._validate_account_payload(
            market_type=normalized["market_type"],
            exchange_code=normalized["exchange_code"],
            api_key=normalized["api_key"],
            api_secret=normalized["api_secret"],
            address_network=normalized["address_network"],
            address_value=normalized["address_value"],
        )

        account_name = self._build_account_name(normalized["exchange_code"], normalized["market_type"])

        try:
            account = account_repository.update_account(
                account_id=account_id,
                user_id=current_user.id,
                market_type=normalized["market_type"],
                exchange_code=normalized["exchange_code"],
                account_name=account_name,
                api_key=normalized["api_key"],
                api_secret=normalized["api_secret"],
                api_passphrase=normalized["api_passphrase"],
                connection_test_status=self._resolve_next_connection_test_status(existing, normalized),
                funding_ratio_percent=float(existing.get("funding_ratio_percent") or 0),
            )
            if account is None:
                raise AccountNotFoundError("账户不存在，或你无权编辑该账户。")

            account_repository.upsert_address(
                account_id=account.id,
                network=normalized["address_network"],
                address_value=normalized["address_value"],
                memo_tag=normalized["address_memo"],
            )
            self._clear_recoverable_auto_transfer_guard_on_account_update(
                user_id=current_user.id,
                account_id=account.id,
                existing=existing,
                normalized=normalized,
            )
        except AccountNotFoundError:
            raise
        except Exception as exc:
            raise AccountPersistenceError("更新账户失败：写入数据库时出错。") from exc

        return AccountCreateResult(account=account)

    def delete_account(self, account_id: int, current_user: AuthUser) -> None:
        try:
            deleted = account_repository.delete_account(account_id=account_id, user_id=current_user.id)
        except Exception as exc:
            raise AccountPersistenceError("删除账户失败：数据库操作异常。") from exc

        if not deleted:
            raise AccountNotFoundError("账户不存在，或你无权删除该账户。")
        account_monitor_service.remove_account(account_id, user_id=current_user.id)

    def mark_connection_test_status(self, account_id: int, current_user: AuthUser, status: str) -> None:
        normalized_status = status.strip().lower()
        if normalized_status not in {"untested", "success", "failed"}:
            raise AccountValidationError("连接测试状态不在支持范围内。")

        try:
            updated = account_repository.update_connection_test_status(
                account_id=account_id,
                user_id=current_user.id,
                status=normalized_status,
            )
        except Exception as exc:
            raise AccountPersistenceError("更新连接测试状态失败：数据库操作异常。") from exc

        if not updated:
            raise AccountNotFoundError("账户不存在，或你无权操作该账户。")

        if normalized_status == "success":
            detail = account_repository.get_account_with_address_by_id(account_id, current_user.id)
            if detail is not None:
                try:
                    snapshot = exchange_connection_service.fetch_balance_snapshot(
                        ExchangeConnectionTestRequest(
                            account_id=account_id,
                            market_type=str(detail.get("market_type") or ""),
                            exchange_code=str(detail.get("exchange_code") or ""),
                            api_key=str(detail.get("api_key") or ""),
                            api_secret=str(detail.get("api_secret") or ""),
                            api_passphrase=str(detail.get("api_passphrase") or ""),
                        )
                    )
                    synced_at = datetime.now()
                    fee_snapshot = exchange_connection_service.fetch_trading_fee_snapshot(
                        ExchangeConnectionTestRequest(
                            account_id=account_id,
                            market_type=str(detail.get("market_type") or ""),
                            exchange_code=str(detail.get("exchange_code") or ""),
                            api_key=str(detail.get("api_key") or ""),
                            api_secret=str(detail.get("api_secret") or ""),
                            api_passphrase=str(detail.get("api_passphrase") or ""),
                        )
                    )
                    account_repository.update_current_available_amount(
                        account_id=account_id,
                        amount=round(float(snapshot.available_amount or 0), 8),
                        synced_at=synced_at,
                    )
                    account_repository.update_fee_rates(
                        account_id=account_id,
                        user_id=current_user.id,
                        maker_fee_rate=round(float(fee_snapshot.maker_fee_rate or 0.05), 6),
                        taker_fee_rate=round(float(fee_snapshot.taker_fee_rate or 0.05), 6),
                        synced_at=synced_at,
                    )
                    account_monitor_service.seed_account(
                        account_id,
                        round(float(snapshot.available_amount or 0), 8),
                        synced_at,
                        user_id=current_user.id,
                        exchange_code=str(detail.get("exchange_code") or ""),
                        market_type=str(detail.get("market_type") or ""),
                        frozen_amount=round(float(snapshot.frozen_amount or 0), 8),
                        total_amount=round(float(snapshot.total_amount or 0), 8),
                    )
                except ExchangeError:
                    pass
                except Exception:
                    pass
            auto_transfer_account_guard_service.clear_non_frozen_account_by_categories(
                current_user.id,
                account_id,
                self.CONNECTION_TEST_SUCCESS_CLEARABLE_GUARD_CATEGORIES,
            )

    def update_funding_ratio_percent(self, account_id: int, current_user: AuthUser, funding_ratio_percent: float) -> None:
        if funding_ratio_percent < 0 or funding_ratio_percent > 100:
            raise AccountValidationError("资金占比必须在 0 到 100 之间。")

        try:
            updated = account_repository.update_funding_ratio_percent(
                account_id=account_id,
                user_id=current_user.id,
                funding_ratio_percent=round(funding_ratio_percent, 2),
            )
        except Exception as exc:
            raise AccountPersistenceError("更新资金占比失败：数据库操作异常。") from exc

        if not updated:
            raise AccountNotFoundError("账户不存在，或你无权操作该账户。")

    def create_transfer_record(
        self,
        payload: AccountTransferCreateRequest,
        current_user: AuthUser,
    ) -> TransferCreateResult:
        if payload.from_account_id <= 0:
            raise AccountValidationError("转出账户不能为空。")
        if payload.to_account_id <= 0:
            raise AccountValidationError("转入账户不能为空。")
        if payload.from_account_id == payload.to_account_id:
            raise AccountValidationError("转出账户和转入账户不能相同。")
        if payload.amount <= 0:
            raise AccountValidationError("划转金额必须大于 0。")

        from_account = account_repository.get_account_with_address_by_id(payload.from_account_id, current_user.id)
        if from_account is None:
            raise AccountNotFoundError("转出账户不存在，或你无权操作该账户。")

        to_account = account_repository.get_account_with_address_by_id(payload.to_account_id, current_user.id)
        if to_account is None:
            raise AccountNotFoundError("转入账户不存在，或你无权操作该账户。")

        reason = str(payload.reason or "").strip() or "手动调拨"

        is_worker_enabled = MANUAL_TRANSFER_EXECUTION_MODE == "worker_enabled"
        result_hint = MANUAL_TRANSFER_EXECUTION_RESULT_HINT

        try:
            transfer_record = account_repository.create_transfer_record(
                user_id=current_user.id,
                from_account_id=payload.from_account_id,
                to_account_id=payload.to_account_id,
                amount=round(payload.amount, 2),
                reason=reason,
                status="pending",
                execute_status="pending_execute",
                result_status="none",
                is_worker_enabled=is_worker_enabled,
                result=result_hint,
            )
        except Exception as exc:
            raise AccountPersistenceError("保存调拨记录失败：数据库操作异常。") from exc

        return TransferCreateResult(transfer_record=transfer_record)

    def _clear_recoverable_auto_transfer_guard_on_account_update(
        self,
        *,
        user_id: int,
        account_id: int,
        existing,
        normalized,
    ) -> None:
        clearable_categories: set[str] = set()
        if self._has_connection_config_changed(existing, normalized):
            clearable_categories.update(self.CONNECTION_UPDATE_CLEARABLE_GUARD_CATEGORIES)
        if self._has_address_config_changed(existing, normalized):
            clearable_categories.update(self.ADDRESS_UPDATE_CLEARABLE_GUARD_CATEGORIES)
        if not clearable_categories:
            return
        auto_transfer_account_guard_service.clear_non_frozen_account_by_categories(
            user_id,
            account_id,
            clearable_categories,
        )

    def _has_connection_config_changed(self, existing, normalized) -> bool:
        return any(
            [
                str(existing.get("market_type") or "").strip().lower() != str(normalized.get("market_type") or "").strip().lower(),
                str(existing.get("exchange_code") or "").strip().lower() != str(normalized.get("exchange_code") or "").strip().lower(),
                str(existing.get("api_key") or "").strip() != str(normalized.get("api_key") or "").strip(),
                str(existing.get("api_secret") or "").strip() != str(normalized.get("api_secret") or "").strip(),
                str(existing.get("api_passphrase") or "").strip() != str(normalized.get("api_passphrase") or "").strip(),
            ]
        )

    def _has_address_config_changed(self, existing, normalized) -> bool:
        return any(
            [
                str(existing.get("network") or "").strip().lower() != str(normalized.get("address_network") or "").strip().lower(),
                str(existing.get("address_value") or "").strip() != str(normalized.get("address_value") or "").strip(),
                str(existing.get("memo_tag") or "").strip() != str(normalized.get("address_memo") or "").strip(),
            ]
        )
