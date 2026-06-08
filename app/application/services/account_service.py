"""Account service for exchange account creation, editing and listing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from app.application.dto.requests import AccountCreateRequest, AccountUpdateRequest
from app.domain.entities import AuthUser, ExchangeAccount
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import (
    AccountNotFoundError,
    AccountPersistenceError,
    AccountValidationError,
)


MARKET_TYPE_LABELS = {
    "spot": "现货",
    "swap": "永续合约",
}

EXCHANGE_LABELS = {
    "binance": "Binance",
    "bitget": "Bitget",
    "okx": "OKX",
    "gate": "Gate",
    "htx": "HTX",
}

NETWORK_LABELS = {
    "": "",
    "trc20": "TRC20",
    "erc20": "ERC20",
    "bep20": "BEP20",
    "arbitrum": "Arbitrum One",
    "optimism": "Optimism",
    "polygon": "Polygon",
    "solana": "Solana",
    "omni": "OMNI",
    "internal": "内部划转",
}


@dataclass(frozen=True)
class AccountCreateResult:
    account: ExchangeAccount


@dataclass(frozen=True)
class AccountDetailResult:
    account_id: int
    market_type: str
    exchange_code: str
    api_key: str
    api_secret: str
    api_passphrase: str
    address_network: str
    address_value: str
    address_memo: str


class AccountService:
    """Coordinates account validation, persistence and page list formatting."""

    def create_account(self, payload: AccountCreateRequest, current_user: AuthUser) -> AccountCreateResult:
        normalized = self._normalize_payload(
            market_type=payload.market_type,
            exchange_code=payload.exchange_code,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            api_passphrase=payload.api_passphrase,
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

        account_name = self._build_account_name(
            normalized["exchange_code"],
            normalized["market_type"],
            current_user.id,
        )

        try:
            account = account_repository.create_account(
                user_id=current_user.id,
                market_type=normalized["market_type"],
                exchange_code=normalized["exchange_code"],
                account_name=account_name,
                api_key=normalized["api_key"],
                api_secret=normalized["api_secret"],
                api_passphrase=normalized["api_passphrase"],
            )
            account_repository.upsert_address(
                account_id=account.id,
                network=normalized["address_network"],
                address_value=normalized["address_value"],
                memo_tag=normalized["address_memo"],
            )
        except Exception as exc:
            raise AccountPersistenceError("保存账户失败：写入数据库时出错。") from exc

        return AccountCreateResult(account=account)

    def get_account_detail(self, account_id: int, current_user: AuthUser) -> AccountDetailResult:
        row = account_repository.get_account_with_address_by_id(account_id, current_user.id)
        if row is None:
            raise AccountNotFoundError("账户不存在，或你无权访问该账户。")

        return AccountDetailResult(
            account_id=int(row["id"]),
            market_type=str(row["market_type"]),
            exchange_code=str(row["exchange_code"]),
            api_key=str(row["api_key"]),
            api_secret=str(row["api_secret"]),
            api_passphrase=str(row["api_passphrase"] or ""),
            address_network=str(row.get("network") or ""),
            address_value=str(row.get("address_value") or ""),
            address_memo=str(row.get("memo_tag") or ""),
        )

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

        account_name = self._build_account_name(
            normalized["exchange_code"],
            normalized["market_type"],
            current_user.id,
        )

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
            )
            if account is None:
                raise AccountNotFoundError("账户不存在，或你无权编辑该账户。")

            account_repository.upsert_address(
                account_id=account.id,
                network=normalized["address_network"],
                address_value=normalized["address_value"],
                memo_tag=normalized["address_memo"],
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

    def build_account_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        rows = account_repository.list_accounts_with_address_by_user_id(user_id)
        result: List[Dict[str, str]] = []

        for row in rows:
            exchange_label = self._exchange_label(str(row["exchange_code"]))
            market_label = self._market_label(str(row["market_type"]))
            api_key = str(row.get("api_key") or "")
            api_secret = str(row.get("api_secret") or "")
            api_passphrase = str(row.get("api_passphrase") or "")
            address_network = str(row.get("network") or "")
            address_value = str(row.get("address_value") or "")
            updated_at = row.get("updated_at")

            result.append(
                {
                    "id": str(row["id"]),
                    "name": str(row["account_name"]),
                    "exchange": exchange_label,
                    "market_type": market_label,
                    "api_key": self._mask_secret(api_key, left=4, right=4),
                    "api_secret": self._mask_secret(api_secret, left=3, right=3),
                    "api_passphrase": "已配置" if api_passphrase else "未配置",
                    "address_status": "已配置" if address_network or address_value else "未配置",
                    "address_status_tone": "positive" if address_network or address_value else "warning",
                    "updated_at": self._format_datetime(updated_at),
                }
            )

        return result

    def build_address_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        rows = account_repository.list_accounts_with_address_by_user_id(user_id)
        result: List[Dict[str, str]] = []

        for row in rows:
            network_code = str(row.get("network") or "")
            address_value = str(row.get("address_value") or "")
            memo_tag = str(row.get("memo_tag") or "")
            if not network_code and not address_value and not memo_tag:
                continue

            result.append(
                {
                    "account": str(row["account_name"]),
                    "exchange": self._exchange_label(str(row["exchange_code"])),
                    "network": self._network_label(network_code) or "未配置",
                    "address": address_value or "--",
                    "memo": memo_tag or "无",
                    "created_at": self._format_datetime(row.get("address_created_at") or row.get("created_at")),
                    "updated_at": self._format_datetime(row.get("address_updated_at") or row.get("updated_at")),
                }
            )

        return result

    def _normalize_payload(
        self,
        *,
        market_type: str,
        exchange_code: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        address_network: str,
        address_value: str,
        address_memo: str,
    ) -> Dict[str, str]:
        return {
            "market_type": market_type.strip().lower(),
            "exchange_code": exchange_code.strip().lower(),
            "api_key": api_key.strip(),
            "api_secret": api_secret.strip(),
            "api_passphrase": api_passphrase.strip(),
            "address_network": address_network.strip().lower(),
            "address_value": address_value.strip(),
            "address_memo": address_memo.strip(),
        }

    def _validate_account_payload(
        self,
        *,
        market_type: str,
        exchange_code: str,
        api_key: str,
        api_secret: str,
        address_network: str,
        address_value: str,
    ) -> None:
        if market_type not in MARKET_TYPE_LABELS:
            raise AccountValidationError("请选择市场类型。")
        if exchange_code not in EXCHANGE_LABELS:
            raise AccountValidationError("请选择交易所。")
        if not api_key:
            raise AccountValidationError("API Key 为必填项。")
        if not api_secret:
            raise AccountValidationError("API Secret 为必填项。")
        if address_value and not address_network:
            raise AccountValidationError("填写接收地址或 UID 时，请先选择网络类型。")
        if address_network and address_network not in NETWORK_LABELS:
            raise AccountValidationError("网络类型不在支持范围内。")

    def _build_account_name(self, exchange_code: str, market_type: str, user_id: int) -> str:
        return f"{self._exchange_label(exchange_code)} {self._market_label(market_type)}账户"

    def _exchange_label(self, exchange_code: str) -> str:
        return EXCHANGE_LABELS.get(exchange_code, exchange_code.upper())

    def _market_label(self, market_type: str) -> str:
        return MARKET_TYPE_LABELS.get(market_type, market_type)

    def _network_label(self, network_code: str) -> str:
        return NETWORK_LABELS.get(network_code, network_code)

    def _mask_secret(self, value: str, *, left: int, right: int) -> str:
        if not value:
            return "--"
        if len(value) <= left + right:
            return value
        return f"{value[:left]}...{value[-right:]}"

    def _format_datetime(self, value: datetime | None) -> str:
        if value is None:
            return "--"
        return value.strftime("%Y-%m-%d %H:%M")


account_service = AccountService()
