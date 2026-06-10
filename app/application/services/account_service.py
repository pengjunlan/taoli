"""Account service for exchange account creation, editing and listing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Dict, List, Optional

from app.application.dto.requests import (
    AccountCreateRequest,
    AccountTransferCreateRequest,
    AccountUpdateRequest,
)
from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.account_monitor_service import account_monitor_service
from app.application.services.exchange_connection_service import exchange_connection_service
from app.domain.entities import AuthUser, ExchangeAccount, TransferRecord
from app.shared.exceptions import ExchangeError
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

FALLBACK_AVAILABLE_AMOUNTS = {
    "binance": "$0",
    "okx": "$0",
    "bitget": "$0",
    "gate": "$0",
    "htx": "$0",
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
    connection_test_status: str
    funding_ratio_percent: float
    address_network: str
    address_value: str
    address_memo: str


@dataclass(frozen=True)
class TransferCreateResult:
    transfer_record: TransferRecord


@dataclass(frozen=True)
class AutoTransferConfigResult:
    is_enabled: bool
    trigger_ratio: float


@dataclass(frozen=True)
class AutoTransferExecutionResult:
    transfer_record: TransferRecord


@dataclass(frozen=True)
class AccountBalanceSnapshot:
    available_value: float
    available_display: str
    is_real: bool


class AccountService:
    """Coordinates account validation, persistence and page list formatting."""

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
            account_monitor_service.seed_account(account.id, 0, None)
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
            connection_test_status=str(row.get("connection_test_status") or "untested"),
            funding_ratio_percent=float(row.get("funding_ratio_percent") or 0),
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
        account_monitor_service.remove_account(account_id)

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
                    amount = exchange_connection_service.fetch_available_balance(
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
                    account_repository.update_current_available_amount(
                        account_id=account_id,
                        amount=round(float(amount or 0), 8),
                        synced_at=synced_at,
                    )
                    account_monitor_service.seed_account(account_id, round(float(amount or 0), 8), synced_at)
                except ExchangeError:
                    pass
                except Exception:
                    pass

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

        try:
            transfer_record = account_repository.create_transfer_record(
                user_id=current_user.id,
                from_account_id=payload.from_account_id,
                to_account_id=payload.to_account_id,
                amount=round(payload.amount, 2),
                reason=reason,
                status="created",
                result="手动调拨已登记，等待后续执行。",
            )
        except Exception as exc:
            raise AccountPersistenceError("保存调拨记录失败：数据库操作异常。") from exc

        return TransferCreateResult(transfer_record=transfer_record)

    def get_auto_transfer_config(self, user_id: int) -> AutoTransferConfigResult:
        row = account_repository.get_auto_transfer_config_by_user_id(user_id)
        if row is None:
            return AutoTransferConfigResult(is_enabled=False, trigger_ratio=0.5)
        return AutoTransferConfigResult(
            is_enabled=bool(row.get("is_enabled")),
            trigger_ratio=float(row.get("trigger_ratio") or 0.5),
        )

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

        account_rows = self.build_account_rows_for_user(current_user.id)
        balance_rows = self.build_balance_rows_from_accounts(account_rows, config.trigger_ratio)
        candidate = self._pick_auto_transfer_candidate(balance_rows, config.trigger_ratio)
        if candidate is None:
            raise AccountValidationError("当前没有满足自动调拨条件的账户。")

        try:
            transfer_record = account_repository.create_transfer_record(
                user_id=current_user.id,
                from_account_id=int(candidate["from_account_id"]),
                to_account_id=int(candidate["to_account_id"]),
                amount=round(float(candidate["amount"]), 2),
                reason="自动调拨",
                status="created",
                result=(
                    f"自动调拨已生成，触发账户低于目标资金的 {int(config.trigger_ratio * 100)}%，"
                    f"本次按最小偏差值登记 {self._format_currency(float(candidate['amount']))}。"
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

    def build_account_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        rows = account_repository.list_accounts_with_address_by_user_id(user_id)
        result: List[Dict[str, str]] = []

        for row in rows:
            exchange_label = self._exchange_label(str(row["exchange_code"]))
            market_label = self._market_label(str(row["market_type"]))
            account_name = self._sanitize_account_name(str(row["account_name"]))
            api_key = str(row.get("api_key") or "")
            api_secret = str(row.get("api_secret") or "")
            api_passphrase = str(row.get("api_passphrase") or "")
            address_network = str(row.get("network") or "")
            address_value = str(row.get("address_value") or "")
            connection_test_status = str(row.get("connection_test_status") or "untested")
            updated_at = row.get("updated_at")
            funding_ratio_percent = float(row.get("funding_ratio_percent") or 0)
            current_available_amount = float(row.get("current_available_amount") or 0)
            current_available_synced_at = row.get("current_available_synced_at")

            result.append(
                {
                    "id": str(row["id"]),
                    "user_id": str(row["user_id"]),
                    "name": account_name,
                    "exchange": exchange_label,
                    "exchange_code": str(row["exchange_code"]),
                    "market_type": market_label,
                    "market_type_code": str(row["market_type"]),
                    "api_key": self._mask_secret(api_key, left=4, right=4),
                    "api_secret": self._mask_secret(api_secret, left=3, right=3),
                    "api_passphrase": "已配置" if api_passphrase else "未配置",
                    "address_status": "已配置" if address_network or address_value else "未配置",
                    "address_status_tone": "positive" if address_network or address_value else "warning",
                    "connection_test_status": self._connection_test_status_label(connection_test_status),
                    "connection_test_status_tone": self._connection_test_status_tone(connection_test_status),
                    "funding_ratio_percent": funding_ratio_percent,
                    "current_available_amount": current_available_amount,
                    "current_available_synced_at": self._format_datetime(current_available_synced_at) if current_available_synced_at else "--",
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
            account_name = self._sanitize_account_name(str(row["account_name"]))
            if not network_code and not address_value and not memo_tag:
                continue

            result.append(
                {
                    "account": account_name,
                    "exchange": self._exchange_label(str(row["exchange_code"])),
                    "network": self._network_label(network_code) or "未配置",
                    "address": address_value or "--",
                    "memo": memo_tag or "无",
                    "created_at": self._format_datetime(row.get("address_created_at") or row.get("created_at")),
                    "updated_at": self._format_datetime(row.get("address_updated_at") or row.get("updated_at")),
                }
            )

        return result

    def build_balance_rows_from_accounts(
        self,
        account_rows: List[Dict[str, str]],
        trigger_ratio: float = 0.5,
    ) -> List[Dict[str, str]]:
        name_to_id_map = {
            str(row.get("name") or "").strip(): str(row.get("id") or "").strip()
            for row in account_rows
            if str(row.get("name") or "").strip()
        }
        available_rows: List[tuple[Dict[str, str], int, str, float]] = []
        total_available_value = 0

        for row in account_rows:
            balance_snapshot = self._resolve_account_balance_snapshot(row)
            available = balance_snapshot.available_display
            available_value = int(round(balance_snapshot.available_value))
            funding_ratio_percent = float(row.get("funding_ratio_percent") or 0)
            available_rows.append((row, available_value, available, funding_ratio_percent))
            total_available_value += available_value

        total_target_pool_value = total_available_value
        total_configured_ratio = sum(item[3] for item in available_rows)
        result: List[Dict[str, str]] = []

        for row, available_value, available, funding_ratio_percent in available_rows:
            exchange = str(row.get("exchange") or "")
            if total_configured_ratio > 0:
                ratio = funding_ratio_percent / total_configured_ratio
            else:
                ratio = (available_value / total_available_value) if total_available_value > 0 else 0
            target_value = int(round(total_target_pool_value * ratio))
            auto_trigger_value = int(round(target_value * trigger_ratio))
            deviation_value = available_value - target_value

            result.append(
                {
                    "id": str(row.get("id") or name_to_id_map.get(str(row.get("name") or "").strip(), "")),
                    "name": str(row.get("name") or "--"),
                    "exchange": exchange or "--",
                    "market_type": str(row.get("market_type") or "--"),
                    "available": available,
                    "allocation_ratio": self._format_percent(funding_ratio_percent / 100) if funding_ratio_percent > 0 else "0%",
                    "funding_ratio_percent": funding_ratio_percent,
                    "target": self._format_amount(target_value),
                    "auto_trigger_value": self._format_amount(auto_trigger_value),
                    "deviation": self._format_amount_with_sign(deviation_value),
                    "address_status": str(row.get("address_status") or "未配置"),
                    "address_status_tone": str(row.get("address_status_tone") or "warning"),
                    "connection_test_status": str(row.get("connection_test_status") or "未测试"),
                    "connection_test_status_tone": str(row.get("connection_test_status_tone") or "warning"),
                    "updated_at": str(row.get("updated_at") or "--"),
                }
            )

        return result

    def build_summary_cards(self, account_rows: List[Dict[str, str]], balance_rows: List[Dict[str, str]], *, is_auto_transfer_enabled: bool) -> List[Dict[str, str]]:
        total_available = sum(self._parse_amount(str(row.get("available") or "$0")) for row in balance_rows)
        imbalance_rows = [
            row for row in balance_rows
            if self._parse_amount(str(row.get("available") or "$0")) < self._parse_amount(str(row.get("target") or "$0"))
        ]

        imbalance_names = " / ".join(str(row.get("exchange") or "--") for row in imbalance_rows[:2]) if imbalance_rows else "当前无低于目标账户"
        auto_config_text = "已开启" if is_auto_transfer_enabled else "已关闭"

        return [
            {"key": "account_count", "label": "参与调度账户", "value": str(len(account_rows)), "change": "全部已纳入资金监控", "tone": "brand"},
            {"key": "total_available", "label": "总可用保证金", "value": self._format_amount(int(round(total_available))), "change": "按当前账户真实可用资金汇总", "tone": "positive"},
            {"key": "imbalance_count", "label": "失衡账户", "value": str(len(imbalance_rows)), "change": imbalance_names, "tone": "warning" if imbalance_rows else "positive"},
            {"key": "auto_transfer_status", "label": "自动均衡", "value": auto_config_text, "change": "按当前触发比例与账户偏差执行", "tone": "brand" if is_auto_transfer_enabled else "neutral"},
        ]

    def build_transfer_rows_for_user(self, user_id: int) -> List[Dict[str, str]]:
        rows = account_repository.list_transfer_records_by_user_id(user_id)
        result: List[Dict[str, str]] = []

        for row in rows:
            result.append(
                {
                    "time": self._format_datetime(row.get("created_at")),
                    "route_from": self._sanitize_account_name(str(row.get("from_account_name") or "--")),
                    "route_to": self._sanitize_account_name(str(row.get("to_account_name") or "--")),
                    "amount": self._format_currency(float(row.get("amount") or 0)),
                    "reason": str(row.get("reason") or "手动调拨"),
                    "status": self._transfer_status_label(str(row.get("status") or "created")),
                    "status_tone": self._transfer_status_tone(str(row.get("status") or "created")),
                    "result": str(row.get("result") or "--"),
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
        connection_test_status: str,
        address_network: str,
        address_value: str,
        address_memo: str,
    ) -> Dict[str, str]:
        normalized_connection_status = connection_test_status.strip().lower()
        if normalized_connection_status not in {"untested", "success", "failed"}:
            normalized_connection_status = "untested"

        return {
            "market_type": market_type.strip().lower(),
            "exchange_code": exchange_code.strip().lower(),
            "api_key": api_key.strip(),
            "api_secret": api_secret.strip(),
            "api_passphrase": api_passphrase.strip(),
            "connection_test_status": normalized_connection_status,
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

    def _build_account_name(self, exchange_code: str, market_type: str) -> str:
        return f"{self._exchange_label(exchange_code)} {self._market_label(market_type)}账户"

    def _pick_auto_transfer_candidate(
        self,
        balance_rows: List[Dict[str, str]],
        trigger_ratio: float,
    ) -> Optional[Dict[str, float]]:
        normalized_rows: List[Dict[str, float | str]] = []
        for row in balance_rows:
            available_value = self._parse_amount(str(row.get("available") or "$0"))
            target_value = self._parse_amount(str(row.get("target") or "$0"))
            deviation_value = available_value - target_value
            normalized_rows.append(
                {
                    "id": str(row.get("id") or ""),
                    "name": str(row.get("name") or "--"),
                    "available_value": float(available_value),
                    "target_value": float(target_value),
                    "deviation_value": float(deviation_value),
                }
            )

        demand_rows = [
            row for row in normalized_rows
            if float(row["target_value"]) > 0 and float(row["available_value"]) < float(row["target_value"]) * trigger_ratio
        ]
        if not demand_rows:
            return None

        demand_rows.sort(key=lambda item: float(item["deviation_value"]))
        source_rows = [
            row for row in normalized_rows
            if float(row["available_value"]) > float(row["target_value"])
        ]
        if not source_rows:
            return None

        source_rows.sort(key=lambda item: float(item["deviation_value"]), reverse=True)
        target_row = demand_rows[0]

        for source_row in source_rows:
            if str(source_row["id"]) == str(target_row["id"]):
                continue

            source_surplus = max(0.0, float(source_row["available_value"]) - float(source_row["target_value"]))
            target_need = max(0.0, float(target_row["target_value"]) - float(target_row["available_value"]))
            transfer_amount = min(source_surplus, target_need)

            if transfer_amount <= 0:
                continue

            source_after = float(source_row["available_value"]) - transfer_amount
            if source_after < float(source_row["target_value"]):
                continue

            return {
                "from_account_id": int(str(source_row["id"])),
                "to_account_id": int(str(target_row["id"])),
                "amount": float(round(transfer_amount, 2)),
            }

        return None

    def _resolve_account_balance_snapshot(self, account_row: Dict[str, str]) -> AccountBalanceSnapshot:
        exchange_name = str(account_row.get("exchange") or "").strip()
        exchange_code = self._resolve_exchange_code(exchange_name)
        account_id = str(account_row.get("id") or "").strip()
        if not account_id or not exchange_code:
            return self._fallback_balance_snapshot(exchange_code)
        try:
            account_id_int = int(account_id)
        except (TypeError, ValueError):
            return self._fallback_balance_snapshot(exchange_code)

        cached_amount = account_monitor_service.get_cached_amount(
            account_id_int,
            fallback_amount=float(account_row.get("current_available_amount") or 0),
        )
        synced_at = account_monitor_service.get_cached_synced_at(account_id_int) or account_row.get("current_available_synced_at")
        if cached_amount > 0 or synced_at is not None:
            return AccountBalanceSnapshot(
                available_value=float(cached_amount),
                available_display=self._format_amount(int(round(cached_amount))),
                is_real=synced_at is not None,
            )

        return self._fallback_balance_snapshot(exchange_code)

    def _fallback_balance_snapshot(self, exchange_code: str) -> AccountBalanceSnapshot:
        display = FALLBACK_AVAILABLE_AMOUNTS.get(exchange_code.lower(), "$0") if exchange_code else "$0"
        return AccountBalanceSnapshot(
            available_value=float(self._parse_amount(display)),
            available_display=display,
            is_real=False,
        )

    def _parse_amount(self, value: str) -> int:
        normalized = str(value or "").strip().upper().replace("$", "").replace(",", "")
        if not normalized:
            return 0
        if normalized.endswith("K"):
            return int(float(normalized[:-1]) * 1000)
        if normalized.endswith("M"):
            return int(float(normalized[:-1]) * 1000000)
        return int(float(normalized))

    def _format_amount_with_sign(self, value: int) -> str:
        prefix = "+" if value > 0 else "-" if value < 0 else ""
        abs_value = abs(value)
        if abs_value >= 1000000:
            text = f"{abs_value / 1000000:.2f}".rstrip("0").rstrip(".")
            return f"{prefix}${text}M"
        if abs_value >= 1000:
            text = f"{abs_value / 1000:.0f}" if abs_value % 1000 == 0 else f"{abs_value / 1000:.1f}".rstrip("0").rstrip(".")
            return f"{prefix}${text}K"
        return f"{prefix}${abs_value}"

    def _format_amount(self, value: int) -> str:
        if value >= 1000000:
            text = f"{value / 1000000:.2f}".rstrip("0").rstrip(".")
            return f"${text}M"
        if value >= 1000:
            text = f"{value / 1000:.0f}" if value % 1000 == 0 else f"{value / 1000:.1f}".rstrip("0").rstrip(".")
            return f"${text}K"
        return f"${value}"

    def _format_currency(self, value: float) -> str:
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
        return f"${text}"

    def _format_percent(self, value: float) -> str:
        return f"{value * 100:.2f}%"

    def _resolve_exchange_code(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in EXCHANGE_LABELS:
            return normalized

        for code, label in EXCHANGE_LABELS.items():
            if normalized == label.lower():
                return code
        return normalized

    def _resolve_market_type_code(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in MARKET_TYPE_LABELS:
            return normalized

        for code, label in MARKET_TYPE_LABELS.items():
            if normalized == label.lower():
                return code
        return normalized

    def _exchange_label(self, exchange_code: str) -> str:
        return EXCHANGE_LABELS.get(exchange_code, exchange_code.upper())

    def _market_label(self, market_type: str) -> str:
        return MARKET_TYPE_LABELS.get(market_type, market_type)

    def _network_label(self, network_code: str) -> str:
        return NETWORK_LABELS.get(network_code, network_code)

    def _connection_test_status_label(self, value: str) -> str:
        return {
            "untested": "未测试",
            "success": "测试成功",
            "failed": "测试失败",
        }.get(value, "未测试")

    def _connection_test_status_tone(self, value: str) -> str:
        return {
            "untested": "warning",
            "success": "positive",
            "failed": "negative",
        }.get(value, "warning")

    def _transfer_status_label(self, value: str) -> str:
        return {
            "created": "已创建",
            "processing": "处理中",
            "success": "已完成",
            "failed": "失败",
        }.get(value, "已创建")

    def _transfer_status_tone(self, value: str) -> str:
        return {
            "created": "brand",
            "processing": "warning",
            "success": "positive",
            "failed": "negative",
        }.get(value, "brand")

    def _resolve_next_connection_test_status(self, existing: Dict[str, str], normalized: Dict[str, str]) -> str:
        return normalized["connection_test_status"] or str(existing.get("connection_test_status") or "untested")

    def _sanitize_account_name(self, value: str) -> str:
        return re.sub(r"\s+U\d+$", "", value).strip()

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
