"""Account service facade for account, query, planning and auto-transfer flows."""

from __future__ import annotations

from typing import Dict, List, Optional

from app.application.dto.requests import (
    AccountCreateRequest,
    AccountTransferCreateRequest,
    AccountUpdateRequest,
)
from app.application.services.account_auto_transfer_service import AccountAutoTransferService
from app.application.services.account_command_service import AccountCommandService
from app.application.services.account_query_service import AccountQueryService
from app.application.services.account_support import (
    AccountBalanceSnapshot,
    AccountCreateResult,
    AccountDetailResult,
    AutoTransferConfigResult,
    AutoTransferExecutionResult,
    MANUAL_TRANSFER_EXECUTION_MODE,
    MANUAL_TRANSFER_EXECUTION_RESULT_HINT,
    TransferCreateResult,
)
from app.application.services.account_transfer_planning_service import AccountTransferPlanningService
from app.domain.entities import AuthUser


class AccountService:
    """Thin facade that keeps the old service API stable while delegating by responsibility."""

    def __init__(self) -> None:
        self._query_service = AccountQueryService()
        self._command_service = AccountCommandService()
        self._transfer_planning_service = AccountTransferPlanningService()
        self._auto_transfer_service = AccountAutoTransferService(
            query_service=self._query_service,
            transfer_planning_service=self._transfer_planning_service,
        )

    def create_account(self, payload: AccountCreateRequest, current_user: AuthUser) -> AccountCreateResult:
        return self._command_service.create_account(payload, current_user)

    def get_account_detail(self, account_id: int, current_user: AuthUser) -> AccountDetailResult:
        return self._query_service.get_account_detail(account_id, current_user.id)

    def list_exchange_network_options(self, exchange_code: str) -> Dict[str, object]:
        return self._query_service.list_exchange_network_options(exchange_code)

    def update_account(
        self,
        account_id: int,
        payload: AccountUpdateRequest,
        current_user: AuthUser,
    ) -> AccountCreateResult:
        return self._command_service.update_account(account_id, payload, current_user)

    def delete_account(self, account_id: int, current_user: AuthUser) -> None:
        self._command_service.delete_account(account_id, current_user)

    def refresh_exchange_network_options(
        self,
        exchange_code: str,
        *,
        market_type: str = "spot",
        api_key: str = "",
        api_secret: str = "",
        api_passphrase: str = "",
    ) -> Dict[str, object]:
        return self._command_service.refresh_exchange_network_options(
            exchange_code,
            market_type=market_type,
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase,
        )

    def mark_connection_test_status(self, account_id: int, current_user: AuthUser, status: str) -> None:
        self._command_service.mark_connection_test_status(account_id, current_user, status)

    def update_funding_ratio_percent(self, account_id: int, current_user: AuthUser, funding_ratio_percent: float) -> None:
        self._command_service.update_funding_ratio_percent(account_id, current_user, funding_ratio_percent)

    def create_transfer_record(
        self,
        payload: AccountTransferCreateRequest,
        current_user: AuthUser,
    ) -> TransferCreateResult:
        return self._command_service.create_transfer_record(payload, current_user)

    def get_auto_transfer_config(self, user_id: int) -> AutoTransferConfigResult:
        return self._auto_transfer_service.get_auto_transfer_config(user_id)

    def update_auto_transfer_config(
        self,
        current_user: AuthUser,
        *,
        is_enabled: bool,
        trigger_ratio: float,
    ) -> AutoTransferConfigResult:
        return self._auto_transfer_service.update_auto_transfer_config(
            current_user,
            is_enabled=is_enabled,
            trigger_ratio=trigger_ratio,
        )

    def execute_auto_transfer(self, current_user: AuthUser) -> AutoTransferExecutionResult:
        return self._auto_transfer_service.execute_auto_transfer(current_user)

    def maybe_execute_auto_transfer(self, user_id: int) -> Optional[AutoTransferExecutionResult]:
        return self._auto_transfer_service.maybe_execute_auto_transfer(user_id)

    def unlock_auto_transfer_account(self, user_id: int, account_id: int) -> None:
        self._auto_transfer_service.unlock_auto_transfer_account(user_id, account_id)

    def build_account_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        return self._query_service.build_account_rows_for_user(user_id)

    def build_active_account_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        return self._query_service.build_active_account_rows_for_user(user_id)

    def build_address_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        return self._query_service.build_address_rows_for_user(user_id)

    def build_balance_rows_from_accounts(
        self,
        account_rows: List[Dict[str, str]],
        trigger_ratio: float = 0.5,
    ) -> List[Dict[str, str]]:
        return self._query_service.build_balance_rows_from_accounts(account_rows, trigger_ratio)

    def build_summary_cards(self, account_rows: List[Dict[str, str]], balance_rows: List[Dict[str, str]], *, is_auto_transfer_enabled: bool) -> List[Dict[str, str]]:
        return self._query_service.build_summary_cards(
            account_rows,
            balance_rows,
            is_auto_transfer_enabled=is_auto_transfer_enabled,
        )

    def build_transfer_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        return self._query_service.build_transfer_rows_for_user(user_id)

    def build_auto_transfer_alert_for_user(self, user_id: int) -> Dict[str, object] | None:
        return self._query_service.build_auto_transfer_alert_for_user(user_id)

    def build_transfer_options_for_user(self, from_account_id: int, user_id: int) -> Dict[str, object]:
        return self._query_service.build_transfer_options_for_user(from_account_id, user_id)

    def _pick_auto_transfer_candidate(
        self,
        balance_rows: List[Dict[str, str]],
        trigger_ratio: float,
    ) -> Optional[Dict[str, float]]:
        return self._transfer_planning_service.pick_auto_transfer_candidate(balance_rows, trigger_ratio)

    @property
    def manual_transfer_execution_mode(self) -> str:
        return MANUAL_TRANSFER_EXECUTION_MODE

    @property
    def manual_transfer_execution_result_hint(self) -> str:
        return MANUAL_TRANSFER_EXECUTION_RESULT_HINT


account_service = AccountService()

__all__ = [
    "AccountBalanceSnapshot",
    "AccountCreateResult",
    "AccountDetailResult",
    "AccountService",
    "AutoTransferConfigResult",
    "AutoTransferExecutionResult",
    "MANUAL_TRANSFER_EXECUTION_MODE",
    "MANUAL_TRANSFER_EXECUTION_RESULT_HINT",
    "TransferCreateResult",
    "account_service",
]
