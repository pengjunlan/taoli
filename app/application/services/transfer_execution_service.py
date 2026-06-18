"""Execute transfer records against exchanges."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Dict

import ccxt

from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.account_support import MANUAL_TRANSFER_EXECUTION_MODE
from app.application.services.exchange_connection_service import exchange_connection_service
from app.shared.exceptions import ExchangeConnectionError, ExchangeError, ExchangeValidationError


logger = logging.getLogger(__name__)

TRANSFER_ASSET_CODE = "USDT"
EXECUTION_MODE = MANUAL_TRANSFER_EXECUTION_MODE

BINANCE_INTERNAL_ACCOUNT_BY_MARKET = {
    "spot": "spot",
    "swap": "linear",
}

OKX_INTERNAL_ACCOUNT_BY_MARKET = {
    "spot": "funding",
    "swap": "trading",
}

NETWORK_ALIASES = {
    "trc20": "TRC20",
    "erc20": "ERC20",
    "bep20": "BEP20",
    "arbitrum": "ARBITRUM",
    "optimism": "OPTIMISM",
    "polygon": "MATIC",
    "plasma": "PLASMA",
    "solana": "SOL",
    "omni": "OMNI",
}


@dataclass(frozen=True)
class TransferExecutionOutcome:
    status: str
    result: str


class TransferExecutionService:
    def execute(self, context: Dict[str, Any]) -> TransferExecutionOutcome:
        self._validate_context(context)

        amount = float(context["amount"] or 0)
        from_exchange = str(context["from_exchange_code"]).strip().lower()
        to_exchange = str(context["to_exchange_code"]).strip().lower()

        if from_exchange == to_exchange and self._is_same_exchange_master_account(context):
            transfer = self._execute_same_exchange_internal_transfer(context, amount)
            return TransferExecutionOutcome(
                status="success",
                result=f"同交易所内部调拨成功，记录号 {self._extract_transfer_reference(transfer)}。",
            )

        withdraw = self._execute_cross_exchange_transfer(context, amount)
        return TransferExecutionOutcome(
            status="success",
            result=f"跨交易所调拨已提交，出金记录号 {self._extract_transfer_reference(withdraw)}。",
        )

    def _validate_context(self, context: Dict[str, Any]) -> None:
        if context is None:
            raise ExchangeValidationError("调拨记录不存在。")
        if not bool(context.get("user_is_active", True)):
            raise ExchangeValidationError("调拨用户已停用，无法执行。")
        if int(context.get("from_user_id") or 0) <= 0 or int(context.get("to_user_id") or 0) <= 0:
            raise ExchangeValidationError("调拨账户不存在。")
        if int(context.get("from_user_id") or 0) != int(context.get("to_user_id") or 0):
            raise ExchangeValidationError("暂不支持跨用户账户调拨。")
        if not bool(context.get("from_is_active")) or not bool(context.get("to_is_active")):
            raise ExchangeValidationError("调拨账户已停用，无法执行。")
        amount = float(context.get("amount") or 0)
        if amount <= 0:
            raise ExchangeValidationError("调拨金额必须大于 0。")

    def _is_same_exchange_master_account(self, context: Dict[str, Any]) -> bool:
        return (
            str(context.get("from_api_key") or "") == str(context.get("to_api_key") or "")
            and str(context.get("from_api_secret") or "") == str(context.get("to_api_secret") or "")
            and str(context.get("from_api_passphrase") or "") == str(context.get("to_api_passphrase") or "")
        )

    def _execute_same_exchange_internal_transfer(self, context: Dict[str, Any], amount: float) -> Dict[str, Any]:
        exchange_code = str(context["from_exchange_code"]).strip().lower()
        from_market_type = str(context["from_market_type"]).strip().lower()
        to_market_type = str(context["to_market_type"]).strip().lower()
        client = self._create_client_from_context(context, prefix="from")

        try:
            if exchange_code == "binance":
                from_account = self._map_binance_account_type(from_market_type)
                to_account = self._map_binance_account_type(to_market_type)
            elif exchange_code == "okx":
                from_account = self._map_okx_account_type(from_market_type)
                to_account = self._map_okx_account_type(to_market_type)
            else:
                raise ExchangeValidationError(f"暂不支持 {exchange_code} 的交易所内调拨。")

            if from_account == to_account:
                raise ExchangeValidationError("源账户与目标账户类型相同，无需执行内部调拨。")

            return client.transfer(TRANSFER_ASSET_CODE, amount, from_account, to_account)
        finally:
            self._close_client(client)

    def _execute_cross_exchange_transfer(self, context: Dict[str, Any], amount: float) -> Dict[str, Any]:
        from_exchange = str(context["from_exchange_code"]).strip().lower()
        to_exchange = str(context["to_exchange_code"]).strip().lower()
        to_market_type = str(context["to_market_type"]).strip().lower()
        to_network = str(context.get("to_network") or "").strip().lower()
        to_address = str(context.get("to_address_value") or "").strip()
        to_memo = str(context.get("to_memo_tag") or "").strip()

        if not to_address:
            raise ExchangeValidationError("目标账户未配置接收地址或 UID，无法执行跨交易所调拨。")
        if to_network in {"", "internal"}:
            raise ExchangeValidationError("跨交易所调拨必须配置可提现网络，不能使用 internal。")

        source_client = self._create_client_from_context(context, prefix="from")
        target_client = self._create_client_from_context(context, prefix="to")

        try:
            source_withdraw_account = self._withdraw_account_for_exchange(from_exchange)
            current_source_account = self._current_account_for_exchange(from_exchange, str(context["from_market_type"]).strip().lower())
            if current_source_account != source_withdraw_account:
                source_client.transfer(TRANSFER_ASSET_CODE, amount, current_source_account, source_withdraw_account)

            destination = self._resolve_destination_address(
                exchange_code=to_exchange,
                target_client=target_client,
                fallback_network=to_network,
                fallback_address=to_address,
                fallback_memo=to_memo,
            )

            withdraw_params = self._build_withdraw_params(
                exchange_code=from_exchange,
                network_code=destination["network_code"],
            )
            withdraw = source_client.withdraw(
                TRANSFER_ASSET_CODE,
                amount,
                destination["address"],
                destination["tag"],
                withdraw_params,
            )

            if to_market_type == "swap":
                balance_before = self._fetch_available_amount(
                    client=target_client,
                    exchange_code=to_exchange,
                    market_type="spot",
                )
                self._wait_for_target_credit(
                    target_client=target_client,
                    exchange_code=to_exchange,
                    market_type="spot",
                    balance_before=balance_before,
                    amount=amount,
                )
                funding_account = self._withdraw_account_for_exchange(to_exchange)
                target_account = self._current_account_for_exchange(to_exchange, to_market_type)
                if funding_account != target_account:
                    target_client.transfer(TRANSFER_ASSET_CODE, amount, funding_account, target_account)

            return withdraw
        finally:
            self._close_client(source_client)
            self._close_client(target_client)

    def _resolve_destination_address(
        self,
        *,
        exchange_code: str,
        target_client: Any,
        fallback_network: str,
        fallback_address: str,
        fallback_memo: str,
    ) -> Dict[str, str | None]:
        normalized_network = self._normalize_network_code(fallback_network)
        if exchange_code == "okx":
            deposit = self._safe_fetch_deposit_address(target_client, normalized_network)
            if deposit is not None:
                info = deposit.get("info") if isinstance(deposit, dict) else None
                to_account = str(info.get("to") or "") if isinstance(info, dict) else ""
                if to_account and to_account not in {"6", "18"}:
                    raise ExchangeValidationError(f"OKX 充值地址目标账户类型异常: {to_account}")
                return {
                    "address": str(deposit.get("address") or fallback_address).strip(),
                    "tag": str(deposit.get("tag") or fallback_memo or "").strip() or None,
                    "network_code": str(deposit.get("network") or normalized_network).strip() or normalized_network,
                }
        if exchange_code == "binance":
            deposit = self._safe_fetch_deposit_address(target_client, normalized_network)
            if deposit is not None:
                return {
                    "address": str(deposit.get("address") or fallback_address).strip(),
                    "tag": str(deposit.get("tag") or fallback_memo or "").strip() or None,
                    "network_code": str(deposit.get("network") or normalized_network).strip() or normalized_network,
                }
        return {
            "address": fallback_address,
            "tag": fallback_memo or None,
            "network_code": normalized_network,
        }

    def _safe_fetch_deposit_address(self, client: Any, network_code: str) -> Dict[str, Any] | None:
        try:
            return client.fetch_deposit_address(TRANSFER_ASSET_CODE, {"network": network_code})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fetch deposit address failed, fallback to saved address: %s", exc)
            return None

    def _wait_for_target_credit(
        self,
        *,
        target_client: Any,
        exchange_code: str,
        market_type: str,
        balance_before: float,
        amount: float,
    ) -> None:
        max_attempts = 18
        sleep_seconds = 10
        for _ in range(max_attempts):
            available_amount = self._fetch_available_amount(
                client=target_client,
                exchange_code=exchange_code,
                market_type=market_type,
            )
            if available_amount - balance_before >= amount * 0.95:
                return
            time.sleep(sleep_seconds)
        raise ExchangeConnectionError("目标交易所到账超时，未能继续转入目标账户。")

    def _fetch_available_amount(self, *, client: Any, exchange_code: str, market_type: str) -> float:
        if exchange_code == "binance":
            balance = client.fetch_balance({"type": "spot" if market_type == "spot" else "swap"})
        elif exchange_code == "okx":
            balance = client.fetch_balance({"type": "funding" if market_type == "spot" else "trading"})
        else:
            balance = client.fetch_balance()
        return float(
            exchange_connection_service._extract_available_balance(  # noqa: SLF001
                balance,
                market_type,
                exchange_code,
            )
        )

    def _build_withdraw_params(self, *, exchange_code: str, network_code: str) -> Dict[str, Any]:
        normalized = self._normalize_network_code(network_code)
        if exchange_code == "binance":
            return {"network": normalized, "walletType": "FUNDING"}
        if exchange_code == "okx":
            fee = "0"
            return {"network": normalized, "fee": fee}
        return {"network": normalized}

    def _create_client_from_context(self, context: Dict[str, Any], *, prefix: str) -> Any:
        payload = ExchangeConnectionTestRequest(
            account_id=int(context.get(f"{prefix}_id") or 0),
            market_type=str(context.get(f"{prefix}_market_type") or ""),
            exchange_code=str(context.get(f"{prefix}_exchange_code") or ""),
            api_key=str(context.get(f"{prefix}_api_key") or ""),
            api_secret=str(context.get(f"{prefix}_api_secret") or ""),
            api_passphrase=str(context.get(f"{prefix}_api_passphrase") or ""),
        )
        return exchange_connection_service.build_exchange_client(payload)

    def _close_client(self, client: Any) -> None:
        try:
            client.close()
        except Exception:
            pass

    def _map_binance_account_type(self, market_type: str) -> str:
        account_type = BINANCE_INTERNAL_ACCOUNT_BY_MARKET.get(market_type)
        if not account_type:
            raise ExchangeValidationError(f"Binance 账户类型不支持: {market_type}")
        return account_type

    def _map_okx_account_type(self, market_type: str) -> str:
        account_type = OKX_INTERNAL_ACCOUNT_BY_MARKET.get(market_type)
        if not account_type:
            raise ExchangeValidationError(f"OKX 账户类型不支持: {market_type}")
        return account_type

    def _withdraw_account_for_exchange(self, exchange_code: str) -> str:
        if exchange_code == "binance":
            return "spot"
        if exchange_code == "okx":
            return "funding"
        raise ExchangeValidationError(f"暂不支持 {exchange_code} 的提现账户映射。")

    def _current_account_for_exchange(self, exchange_code: str, market_type: str) -> str:
        if exchange_code == "binance":
            return self._map_binance_account_type(market_type)
        if exchange_code == "okx":
            return self._map_okx_account_type(market_type)
        raise ExchangeValidationError(f"暂不支持 {exchange_code} 的账户类型映射。")

    def _normalize_network_code(self, network_code: str) -> str:
        normalized = str(network_code or "").strip().lower()
        if not normalized:
            raise ExchangeValidationError("未配置提现网络。")
        return NETWORK_ALIASES.get(normalized, normalized.upper())

    def _extract_transfer_reference(self, response: Dict[str, Any] | None) -> str:
        if not isinstance(response, dict):
            return "--"
        for key in ("id", "txid", "txId", "wdId", "transId", "tranId"):
            value = response.get(key)
            if value:
                return str(value)
        info = response.get("info")
        if isinstance(info, dict):
            for key in ("id", "txId", "wdId", "transId", "tranId"):
                value = info.get(key)
                if value:
                    return str(value)
        return "--"


transfer_execution_service = TransferExecutionService()
