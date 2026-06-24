"""Read-side account service logic."""

from __future__ import annotations

from typing import Dict, List

from app.application.services.auto_transfer_account_guard_service import auto_transfer_account_guard_service
from app.application.services.exchange_asset_network_service import exchange_asset_network_service
from app.application.services.account_support import (
    AccountDetailResult,
    AccountServiceSupport,
    AutoTransferConfigResult,
)
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import AccountNotFoundError
from app.views.presenters.account_presenter import AccountPresenter


class AccountQueryService(AccountServiceSupport):
    def __init__(self) -> None:
        self._presenter = AccountPresenter()

    def build_active_account_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        rows = account_repository.list_active_accounts_with_address_by_user_id(user_id)
        return self._build_account_rows(rows, user_id=user_id)

    def get_account_detail(self, account_id: int, user_id: int) -> AccountDetailResult:
        row = account_repository.get_account_with_address_by_id(account_id, user_id)
        if row is None:
            raise AccountNotFoundError("账户不存在，或你无权访问该账户。")

        return AccountDetailResult(
            account_id=int(row["id"]),
            market_type=str(row["market_type"]),
            exchange_code=str(row["exchange_code"]),
            api_key=str(row["api_key"]),
            api_secret=str(row["api_secret"]),
            api_passphrase=str(row["api_passphrase"] or ""),
            connection_test_status=str(row.get("connection_test_status") or "untested"),
            funding_ratio_percent=float(row.get("funding_ratio_percent") or 0),
            maker_fee_rate=float(row.get("maker_fee_rate") or 0.05),
            taker_fee_rate=float(row.get("taker_fee_rate") or 0.05),
            fee_rate_synced_at=row.get("fee_rate_synced_at"),
            address_network=str(row.get("network") or ""),
            address_value=str(row.get("address_value") or ""),
            address_memo=str(row.get("memo_tag") or ""),
        )

    def list_exchange_network_options(self, exchange_code: str) -> Dict[str, object]:
        return exchange_asset_network_service.list_network_options(exchange_code)

    def get_auto_transfer_config(self, user_id: int) -> AutoTransferConfigResult:
        row = account_repository.get_auto_transfer_config_by_user_id(user_id)
        if row is None:
            return AutoTransferConfigResult(is_enabled=False, trigger_ratio=0.5)
        return AutoTransferConfigResult(
            is_enabled=bool(row.get("is_enabled")),
            trigger_ratio=float(row.get("trigger_ratio") or 0.5),
        )

    def build_account_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        rows = account_repository.list_accounts_with_address_by_user_id(user_id)
        return self._build_account_rows(rows, user_id=user_id)

    def _build_account_rows(self, rows: List[Dict[str, str]], user_id: int | None = None) -> List[Dict[str, str]]:
        guard_states = auto_transfer_account_guard_service.list_states(int(user_id or 0)) if user_id else {}
        return self._presenter.build_account_rows(rows, guard_states=guard_states)

    def build_address_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        rows = account_repository.list_accounts_with_address_by_user_id(user_id)
        return self._presenter.build_address_rows(rows)

    def build_balance_rows_from_accounts(
        self,
        account_rows: List[Dict[str, str]],
        trigger_ratio: float = 0.5,
    ) -> List[Dict[str, str]]:
        return self._presenter.build_balance_rows(account_rows, trigger_ratio)

    def build_summary_cards(
        self,
        account_rows: List[Dict[str, str]],
        balance_rows: List[Dict[str, str]],
        *,
        is_auto_transfer_enabled: bool,
    ) -> List[Dict[str, str]]:
        return self._presenter.build_summary_cards(
            account_rows,
            balance_rows,
            is_auto_transfer_enabled=is_auto_transfer_enabled,
        )

    def build_transfer_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        rows = account_repository.list_transfer_records_by_user_id(user_id)
        return self._presenter.build_transfer_rows(rows)

    def build_auto_transfer_alert_for_user(self, user_id: int) -> Dict[str, object] | None:
        alert = auto_transfer_account_guard_service.build_alert_summary(user_id)
        if not alert:
            return None

        return {
            "level": str(alert.get("level") or "warning"),
            "message": str(alert.get("message") or ""),
            "account_id": int(alert.get("account_id") or 0),
            "account_name": str(alert.get("account_name") or ""),
            "error_label": str(alert.get("error_label") or ""),
            "raw_message": str(alert.get("raw_message") or ""),
            "is_frozen": bool(alert.get("is_frozen")),
            "consecutive_count": int(alert.get("consecutive_count") or 0),
            "last_error_at": str(alert.get("last_error_at") or "--"),
        }

    def build_transfer_options_for_user(self, from_account_id: int, user_id: int) -> Dict[str, object]:
        rows = account_repository.list_accounts_with_address_by_user_id(user_id)
        from_account = next((row for row in rows if int(row["id"]) == int(from_account_id)), None)
        if from_account is None:
            raise AccountNotFoundError("转出账户不存在，或你无权操作该账户。")
        return self._presenter.build_transfer_options(from_account=from_account, rows=rows)
