"""Execute transfer records against exchanges."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time
from typing import Any, Dict

import ccxt

from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.account_support import MANUAL_TRANSFER_EXECUTION_MODE
from app.application.services.exchange_connection_service import exchange_connection_service
from app.application.services.exchange_transfer_adapters import (
    DepositDestination,
    ExchangeTransferAdapter,
    exchange_transfer_registry,
)
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import ExchangeConnectionError, ExchangeError, ExchangeValidationError


logger = logging.getLogger(__name__)

TRANSFER_ASSET_CODE = "USDT"
EXECUTION_MODE = MANUAL_TRANSFER_EXECUTION_MODE
ROLLBACK_RESULT_PREFIX = "跨交易所提现失败，已将资金回滚至原账户。"
CHECKPOINT_SAME_EXCHANGE_COMPLETED = "same_exchange_completed"
CHECKPOINT_SOURCE_INTERNAL_PREPARED = "source_internal_prepared"
CHECKPOINT_WITHDRAW_SUBMITTED = "withdraw_submitted"
CHECKPOINT_TARGET_CREDIT_CONFIRMED = "target_credit_confirmed"
CHECKPOINT_TARGET_INTERNAL_TRANSFERRED = "target_internal_transferred"

@dataclass(frozen=True)
class TransferExecutionOutcome:
    status: str
    result: str
    execute_status: str = "processed"
    result_status: str = "success"
    failure_type: str = ""
    failure_reason: str = ""
    execution_checkpoint: str | None = None
    execution_reference: str | None = None
    execution_payload: str | None = None


class TransferExecutionService:
    AUTO_TRANSFER_FAILURE_META = {
        "permission_denied": {
            "label": "权限不足",
            "freeze_worthy": True,
            "responsible_side": "from",
        },
        "api_auth_failed": {
            "label": "API 认证失败",
            "freeze_worthy": True,
            "responsible_side": "from",
        },
        "ip_whitelist_blocked": {
            "label": "IP 白名单限制",
            "freeze_worthy": True,
            "responsible_side": "from",
        },
        "withdraw_disabled": {
            "label": "提现权限异常",
            "freeze_worthy": True,
            "responsible_side": "from",
        },
        "address_invalid": {
            "label": "接收地址或 UID 异常",
            "freeze_worthy": True,
            "responsible_side": "to",
        },
        "network_invalid": {
            "label": "网络或 Memo 配置异常",
            "freeze_worthy": True,
            "responsible_side": "to",
        },
        "deposit_info_invalid": {
            "label": "充值信息异常",
            "freeze_worthy": True,
            "responsible_side": "to",
        },
        "account_mapping_invalid": {
            "label": "账户类型映射异常",
            "freeze_worthy": True,
            "responsible_side": "from",
        },
        "route_unsupported": {
            "label": "调拨路径不支持",
            "freeze_worthy": False,
            "responsible_side": "from",
        },
        "temporary_network": {
            "label": "网络临时异常",
            "freeze_worthy": False,
            "responsible_side": "from",
        },
        "temporary_exchange": {
            "label": "交易所临时异常",
            "freeze_worthy": False,
            "responsible_side": "from",
        },
        "unknown": {
            "label": "未知异常",
            "freeze_worthy": False,
            "responsible_side": "from",
        },
    }

    USER_ACCOUNT_FAILURE_HINTS = (
        "api key",
        "api secret",
        "passphrase",
        "签名",
        "密钥",
        "权限",
        "白名单",
        "ip",
        "restricted ip",
        "地址",
        "uid",
        "网络",
        "账户类型",
        "账户映射",
        "提现",
        "充值",
        "未配置",
        "不支持",
        "unsupported",
        "停用",
    )

    def execute(self, context: Dict[str, Any]) -> TransferExecutionOutcome:
        try:
            self._validate_context(context)

            amount = float(context["amount"] or 0)
            from_exchange = str(context["from_exchange_code"]).strip().lower()
            to_exchange = str(context["to_exchange_code"]).strip().lower()

            if from_exchange == to_exchange and self._is_same_exchange_master_account(context):
                transfer = self._execute_same_exchange_internal_transfer(context, amount)
                return TransferExecutionOutcome(
                    status="success",
                    result=f"同交易所内部调拨成功，记录号 {self._extract_transfer_reference(transfer)}。",
                    execution_checkpoint=CHECKPOINT_SAME_EXCHANGE_COMPLETED,
                    execution_reference=self._extract_transfer_reference(transfer),
                )

            return self._execute_cross_exchange_transfer(context, amount)
        except ExchangeError:
            raise
        except ccxt.AuthenticationError as exc:
            raise ExchangeConnectionError(self._translate_exchange_exception_message(exc)) from exc
        except ccxt.PermissionDenied as exc:
            raise ExchangeConnectionError(self._translate_exchange_exception_message(exc)) from exc
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError(self._translate_exchange_exception_message(exc)) from exc
        except ccxt.ExchangeError as exc:
            raise ExchangeConnectionError(self._translate_exchange_exception_message(exc)) from exc

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
        from_exchange = str(context.get("from_exchange_code") or "").strip().lower()
        to_exchange = str(context.get("to_exchange_code") or "").strip().lower()
        if self._get_exchange_adapter(from_exchange) is None:
            raise ExchangeValidationError(f"暂不支持 {from_exchange or '--'} 的真实调拨执行。")
        if self._get_exchange_adapter(to_exchange) is None:
            raise ExchangeValidationError(f"暂不支持 {to_exchange or '--'} 的真实调拨执行。")

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
        adapter = self._get_exchange_adapter_or_raise(exchange_code)
        client = self._create_client_from_context(
            context,
            prefix="from",
            market_type_override=adapter.transfer_client_market_type,
        )

        try:
            from_account = self._map_internal_account(adapter, exchange_code, from_market_type)
            to_account = self._map_internal_account(adapter, exchange_code, to_market_type)

            if from_account == to_account:
                raise ExchangeValidationError("源账户与目标账户类型相同，无需执行内部调拨。")

            return client.transfer(TRANSFER_ASSET_CODE, amount, from_account, to_account)
        finally:
            self._close_client(client)

    def _execute_cross_exchange_transfer(self, context: Dict[str, Any], amount: float) -> TransferExecutionOutcome:
        from_exchange = str(context["from_exchange_code"]).strip().lower()
        to_exchange = str(context["to_exchange_code"]).strip().lower()
        from_market_type = str(context["from_market_type"]).strip().lower()
        to_market_type = str(context["to_market_type"]).strip().lower()
        to_network = str(context.get("to_network") or "").strip()
        to_address = str(context.get("to_address_value") or "").strip()
        to_memo = str(context.get("to_memo_tag") or "").strip()
        source_adapter = self._get_exchange_adapter_or_raise(from_exchange)
        target_adapter = self._get_exchange_adapter_or_raise(to_exchange)
        checkpoint = str(context.get("execution_checkpoint") or "").strip()

        if not to_address:
            raise ExchangeValidationError("目标账户未配置接收地址或 UID，无法执行跨交易所调拨。")
        if not to_network or to_network.lower() == "internal":
            raise ExchangeValidationError("跨交易所调拨必须配置可提现网络，不能使用 internal。")

        source_client = self._create_client_from_context(
            context,
            prefix="from",
            market_type_override=source_adapter.transfer_client_market_type,
        )
        target_client = self._create_client_from_context(
            context,
            prefix="to",
            market_type_override=target_adapter.transfer_client_market_type,
        )

        moved_to_withdraw_account = False
        source_withdraw_account = source_adapter.withdraw_account
        current_source_account = self._map_internal_account(source_adapter, from_exchange, from_market_type)
        withdraw_network_code = source_adapter.resolve_withdraw_network_code(to_network)
        withdraw_fee = 0.0
        withdraw_reference = str(context.get("execution_reference") or "").strip()

        try:
            if checkpoint not in {CHECKPOINT_WITHDRAW_SUBMITTED, CHECKPOINT_TARGET_CREDIT_CONFIRMED, CHECKPOINT_TARGET_INTERNAL_TRANSFERRED}:
                withdraw_fee = self._resolve_withdraw_fee(
                    client=source_client,
                    adapter=source_adapter,
                    network_code=withdraw_network_code,
                )
                transfer_amount_to_withdraw_account = amount + withdraw_fee
                if current_source_account != source_withdraw_account:
                    source_client.transfer(
                        TRANSFER_ASSET_CODE,
                        transfer_amount_to_withdraw_account,
                        current_source_account,
                        source_withdraw_account,
                    )
                    moved_to_withdraw_account = True
                self._store_execution_checkpoint(
                    context,
                    execution_checkpoint=CHECKPOINT_SOURCE_INTERNAL_PREPARED,
                )
            else:
                withdraw_fee = self._resolve_withdraw_fee(
                    client=source_client,
                    adapter=source_adapter,
                    network_code=withdraw_network_code,
                )

            destination = self._resolve_destination_address(
                adapter=target_adapter,
                target_client=target_client,
                fallback_network=to_network,
                fallback_address=to_address,
                fallback_memo=to_memo,
            )
            self._store_resolved_destination(context, destination)

            if checkpoint not in {CHECKPOINT_WITHDRAW_SUBMITTED, CHECKPOINT_TARGET_CREDIT_CONFIRMED, CHECKPOINT_TARGET_INTERNAL_TRANSFERRED}:
                withdraw_params = self._build_withdraw_params(
                    adapter=source_adapter,
                    network_code=destination.network_code,
                    fee=withdraw_fee,
                )
                withdraw = source_client.withdraw(
                    TRANSFER_ASSET_CODE,
                    amount,
                    destination.address,
                    destination.tag,
                    withdraw_params,
                )
                withdraw_reference = self._extract_transfer_reference(withdraw)
                self._store_withdraw_submission(context, withdraw, withdraw_reference)

            if to_market_type == "swap" and checkpoint not in {CHECKPOINT_TARGET_CREDIT_CONFIRMED, CHECKPOINT_TARGET_INTERNAL_TRANSFERRED}:
                target_credit_market_type = target_adapter.withdraw_account_market_type
                balance_before = self._read_target_credit_balance_before(context)
                if balance_before is None:
                    balance_before = self._fetch_available_amount(
                        client=target_client,
                        adapter=target_adapter,
                        market_type=target_credit_market_type,
                    )
                    self._store_execution_checkpoint(
                        context,
                        execution_checkpoint=CHECKPOINT_WITHDRAW_SUBMITTED,
                        execution_reference=withdraw_reference,
                        execution_payload=self._serialize_execution_payload_meta(
                            context,
                            target_credit_balance_before=balance_before,
                        ),
                    )
                self._wait_for_target_credit(
                    target_client=target_client,
                    adapter=target_adapter,
                    market_type=target_credit_market_type,
                    balance_before=balance_before,
                    amount=amount,
                )
                self._store_execution_checkpoint(
                    context,
                    execution_checkpoint=CHECKPOINT_TARGET_CREDIT_CONFIRMED,
                    execution_reference=withdraw_reference,
                )

            if to_market_type == "swap" and checkpoint != CHECKPOINT_TARGET_INTERNAL_TRANSFERRED:
                funding_account = target_adapter.withdraw_account
                target_account = self._map_internal_account(target_adapter, to_exchange, to_market_type)
                if funding_account != target_account:
                    target_client.transfer(TRANSFER_ASSET_CODE, amount, funding_account, target_account)
                self._store_execution_checkpoint(
                    context,
                    execution_checkpoint=CHECKPOINT_TARGET_INTERNAL_TRANSFERRED,
                    execution_reference=withdraw_reference,
                )

            return TransferExecutionOutcome(
                status="success",
                result=f"跨交易所调拨已提交，出金记录号 {withdraw_reference}。",
                execution_checkpoint=(
                    CHECKPOINT_TARGET_INTERNAL_TRANSFERRED
                    if to_market_type == "swap"
                    else CHECKPOINT_WITHDRAW_SUBMITTED
                ),
                execution_reference=withdraw_reference,
                execution_payload=self._serialize_execution_payload_meta(context) or None,
            )
        except ExchangeConnectionError as exc:
            if self._withdraw_submitted(context) or checkpoint in {
                CHECKPOINT_WITHDRAW_SUBMITTED,
                CHECKPOINT_TARGET_CREDIT_CONFIRMED,
                CHECKPOINT_TARGET_INTERNAL_TRANSFERRED,
            }:
                if checkpoint not in {
                    CHECKPOINT_WITHDRAW_SUBMITTED,
                    CHECKPOINT_TARGET_CREDIT_CONFIRMED,
                    CHECKPOINT_TARGET_INTERNAL_TRANSFERRED,
                }:
                    self._store_execution_checkpoint(
                        context,
                        execution_checkpoint=CHECKPOINT_WITHDRAW_SUBMITTED,
                        execution_reference=str(context.get("_withdraw_reference") or withdraw_reference),
                        execution_payload=str(context.get("_withdraw_payload") or ""),
                    )
                return TransferExecutionOutcome(
                    status="processing",
                    result=self._build_post_withdraw_pending_message(context=context, error=exc),
                    execute_status="pending_execute",
                    result_status="none",
                    failure_type="",
                    failure_reason="",
                    execution_checkpoint=str(context.get("execution_checkpoint") or CHECKPOINT_WITHDRAW_SUBMITTED),
                    execution_reference=str(context.get("execution_reference") or context.get("_withdraw_reference") or withdraw_reference),
                    execution_payload=self._serialize_execution_payload_meta(context) or None,
                )
            raise
        except Exception as exc:
            rollback_result = None
            if moved_to_withdraw_account and not self._withdraw_submitted(context):
                rollback_result = self._rollback_source_internal_transfer(
                    source_client=source_client,
                    exchange_code=from_exchange,
                    current_source_account=current_source_account,
                    source_withdraw_account=source_withdraw_account,
                    amount=amount,
                )
                if rollback_result["rolled_back"]:
                    raise ExchangeConnectionError(
                        self._build_rollback_success_message(exc, rollback_result["detail"])
                    ) from exc
                if rollback_result["attempted"]:
                    raise ExchangeConnectionError(
                        self._build_rollback_failed_message(
                            original_error=exc,
                            rollback_error_message=rollback_result["detail"],
                        )
                    ) from exc
            raise
        finally:
            self._close_client(source_client)
            self._close_client(target_client)

    def _resolve_destination_address(
        self,
        *,
        adapter: ExchangeTransferAdapter,
        target_client: Any,
        fallback_network: str,
        fallback_address: str,
        fallback_memo: str,
    ) -> DepositDestination:
        requested_network = str(fallback_network or "").strip()
        if not requested_network:
            raise ExchangeValidationError("未配置提现网络。")
        deposit = self._safe_fetch_deposit_address(adapter=adapter, client=target_client, network_code=requested_network)
        try:
            return adapter.resolve_deposit_destination(
                deposit=deposit,
                fallback_network=fallback_network,
                fallback_address=fallback_address,
                fallback_memo=fallback_memo,
            )
        except ValueError as exc:
            raise ExchangeValidationError(str(exc)) from exc

    def _safe_fetch_deposit_address(
        self,
        *,
        adapter: ExchangeTransferAdapter,
        client: Any,
        network_code: str,
    ) -> Dict[str, Any] | None:
        try:
            return adapter.fetch_deposit_address(client, network_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fetch deposit address failed, fallback to saved address: %s", exc)
            return None

    def _wait_for_target_credit(
        self,
        *,
        target_client: Any,
        adapter: ExchangeTransferAdapter,
        market_type: str,
        balance_before: float,
        amount: float,
    ) -> None:
        max_attempts = 18
        sleep_seconds = 10
        for _ in range(max_attempts):
            available_amount = self._fetch_available_amount(
                client=target_client,
                adapter=adapter,
                market_type=market_type,
            )
            if available_amount - balance_before >= amount * 0.95:
                return
            time.sleep(sleep_seconds)
        raise ExchangeConnectionError("目标交易所到账超时，未能继续转入目标账户。")

    def _fetch_available_amount(self, *, client: Any, adapter: ExchangeTransferAdapter, market_type: str) -> float:
        balance_params = adapter.build_balance_params(market_type)
        balance = client.fetch_balance(balance_params) if balance_params is not None else client.fetch_balance()
        return float(
            exchange_connection_service._extract_available_balance(  # noqa: SLF001
                balance,
                market_type,
                adapter.code,
            )
        )

    def _resolve_withdraw_fee(self, *, client: Any, adapter: ExchangeTransferAdapter, network_code: str) -> float:
        resolved_network = adapter.resolve_withdraw_network_code(network_code)
        try:
            currencies = client.fetch_currencies()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fetch currencies failed when resolving withdraw fee: exchange=%s detail=%s", adapter.code, exc)
            return 0.0

        currency = currencies.get(TRANSFER_ASSET_CODE) or {}
        networks = currency.get("networks") or {}
        network = networks.get(resolved_network) or {}
        fee = network.get("fee")
        try:
            return max(float(fee or 0), 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _build_withdraw_params(
        self,
        *,
        adapter: ExchangeTransferAdapter,
        network_code: str,
        fee: float | None = None,
    ) -> Dict[str, Any]:
        return adapter.build_withdraw_params(network_code, fee)

    def _create_client_from_context(
        self,
        context: Dict[str, Any],
        *,
        prefix: str,
        market_type_override: str | None = None,
    ) -> Any:
        payload = ExchangeConnectionTestRequest(
            account_id=int(context.get(f"{prefix}_id") or 0),
            market_type=str(market_type_override or context.get(f"{prefix}_market_type") or ""),
            exchange_code=str(context.get(f"{prefix}_exchange_code") or ""),
            api_key=str(context.get(f"{prefix}_api_key") or ""),
            api_secret=str(context.get(f"{prefix}_api_secret") or ""),
            api_passphrase=str(context.get(f"{prefix}_api_passphrase") or ""),
        )
        return exchange_connection_service.build_exchange_client(payload)

    def _close_client(self, client: Any) -> None:
        try:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        except Exception:
            pass

    def _rollback_source_internal_transfer(
        self,
        *,
        source_client: Any,
        exchange_code: str,
        current_source_account: str,
        source_withdraw_account: str,
        amount: float,
    ) -> Dict[str, Any]:
        if current_source_account == source_withdraw_account:
            return {
                "attempted": False,
                "rolled_back": False,
                "detail": "",
            }

        try:
            source_client.transfer(TRANSFER_ASSET_CODE, amount, source_withdraw_account, current_source_account)
            return {
                "attempted": True,
                "rolled_back": True,
                "detail": f"{source_withdraw_account} -> {current_source_account}",
            }
        except Exception as rollback_exc:  # noqa: BLE001
            logger.exception(
                "Rollback source internal transfer failed: exchange=%s from=%s to=%s amount=%s",
                exchange_code,
                source_withdraw_account,
                current_source_account,
                amount,
            )
            return {
                "attempted": True,
                "rolled_back": False,
                "detail": str(rollback_exc or "").strip() or "回滚失败，交易所未返回更多信息。",
            }

    def _build_rollback_success_message(self, original_error: Exception, rollback_detail: str) -> str:
        original_message = self._translate_exchange_exception_message(original_error)
        detail = str(rollback_detail or "").strip()
        if detail:
            return f"{ROLLBACK_RESULT_PREFIX} 回滚路径：{detail}。原始失败原因：{original_message}"
        return f"{ROLLBACK_RESULT_PREFIX} 原始失败原因：{original_message}"

    def _build_rollback_failed_message(self, *, original_error: Exception, rollback_error_message: str) -> str:
        original_message = self._translate_exchange_exception_message(original_error)
        rollback_message = str(rollback_error_message or "").strip() or "回滚失败，交易所未返回更多信息。"
        return (
            "跨交易所提现失败，且源交易所内部资金回滚失败，资金可能滞留在提现账户。\n"
            f"原始失败原因：{original_message}\n"
            f"回滚失败原因：{rollback_message}"
        )

    def _store_resolved_destination(self, context: Dict[str, Any], destination: DepositDestination) -> None:
        context["_resolved_to_network"] = str(destination.network_code or "").strip()
        context["_resolved_to_address_value"] = str(destination.address or "").strip()
        context["_resolved_to_memo_tag"] = str(destination.tag or "").strip()

    def _store_withdraw_submission(self, context: Dict[str, Any], withdraw: Dict[str, Any] | None, reference: str) -> None:
        context["_withdraw_submitted"] = True
        context["_withdraw_reference"] = str(reference or "").strip()
        if isinstance(withdraw, dict):
            try:
                context["_withdraw_payload"] = json.dumps(withdraw, ensure_ascii=False, default=str)
            except Exception:
                context["_withdraw_payload"] = ""
        self._store_execution_checkpoint(
            context,
            execution_checkpoint=CHECKPOINT_WITHDRAW_SUBMITTED,
            execution_reference=str(context.get("_withdraw_reference") or "").strip(),
            execution_payload=str(context.get("_withdraw_payload") or ""),
        )

    def _withdraw_submitted(self, context: Dict[str, Any]) -> bool:
        return bool(context.get("_withdraw_submitted"))

    def _build_post_withdraw_pending_message(self, *, context: Dict[str, Any], error: Exception) -> str:
        withdraw_reference = str(context.get("_withdraw_reference") or "").strip() or "--"
        return (
            f"跨交易所提现已提交，出金记录号 {withdraw_reference}。"
            f"目标交易所到账或自动划转仍在处理中，请稍后刷新确认。当前提示：{self._translate_exchange_exception_message(error)}"
        )

    def _get_exchange_adapter(self, exchange_code: str) -> ExchangeTransferAdapter | None:
        return exchange_transfer_registry.get(exchange_code)

    def _get_exchange_adapter_or_raise(self, exchange_code: str) -> ExchangeTransferAdapter:
        adapter = self._get_exchange_adapter(exchange_code)
        if adapter is None:
            raise ExchangeValidationError(f"暂不支持 {exchange_code} 的真实调拨执行。")
        return adapter

    def _map_internal_account(self, adapter: ExchangeTransferAdapter, exchange_code: str, market_type: str) -> str:
        account_type = adapter.map_internal_account(market_type)
        if not account_type:
            raise ExchangeValidationError(f"{exchange_code.upper()} 账户类型不支持: {market_type}")
        return account_type

    def _store_execution_checkpoint(
        self,
        context: Dict[str, Any],
        *,
        execution_checkpoint: str,
        execution_reference: str = "",
        execution_payload: str = "",
    ) -> None:
        context["execution_checkpoint"] = execution_checkpoint
        if execution_reference:
            context["execution_reference"] = execution_reference
        if execution_payload:
            context["execution_payload"] = execution_payload
        record_id = int(context.get("id") or 0)
        if record_id > 0:
            account_repository.update_transfer_record_execution_checkpoint(
                record_id,
                execution_checkpoint=execution_checkpoint,
                execution_reference=str(context.get("execution_reference") or execution_reference),
                execution_payload=str(context.get("execution_payload") or execution_payload),
            )

    def _serialize_execution_payload_meta(
        self,
        context: Dict[str, Any],
        *,
        target_credit_balance_before: float | None = None,
    ) -> str:
        payload: Dict[str, Any] = {}
        raw_payload = context.get("_withdraw_payload") or context.get("execution_payload") or ""
        if raw_payload:
            try:
                parsed = json.loads(str(raw_payload))
                if isinstance(parsed, dict):
                    payload.update(parsed)
            except Exception:
                payload["raw"] = str(raw_payload)
        if target_credit_balance_before is not None:
            payload["_target_credit_balance_before"] = float(target_credit_balance_before)
        text = json.dumps(payload, ensure_ascii=False, default=str) if payload else ""
        if text:
            context["execution_payload"] = text
        return text

    def _read_target_credit_balance_before(self, context: Dict[str, Any]) -> float | None:
        raw_payload = context.get("execution_payload") or context.get("_withdraw_payload") or ""
        if not raw_payload:
            return None
        try:
            parsed = json.loads(str(raw_payload))
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
        value = parsed.get("_target_credit_balance_before")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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

    def is_user_account_failure(self, error: Exception) -> bool:
        if isinstance(error, ExchangeValidationError):
            return True
        if not isinstance(error, ExchangeConnectionError):
            return False

        message = str(error or "").strip().lower()
        return any(hint in message for hint in self.USER_ACCOUNT_FAILURE_HINTS)

    def classify_auto_transfer_failure(self, context: Dict[str, Any], error: Exception) -> Dict[str, Any]:
        category = self._normalize_failure_category(error)
        meta = self.AUTO_TRANSFER_FAILURE_META.get(category, self.AUTO_TRANSFER_FAILURE_META["unknown"])
        responsible_side = str(meta.get("responsible_side") or "from").strip().lower()
        account_id = int(context.get(f"{responsible_side}_account_id") or context.get(f"{responsible_side}_id") or 0)
        account_name = str(context.get(f"{responsible_side}_account_name") or "").strip()
        exchange_code = str(context.get(f"{responsible_side}_exchange_code") or "").strip().lower()
        return {
            "category": category,
            "label": str(meta.get("label") or "未知异常"),
            "freeze_worthy": bool(meta.get("freeze_worthy")),
            "responsible_side": responsible_side,
            "account_id": account_id,
            "account_name": account_name,
            "exchange_code": exchange_code,
            "raw_message": str(error or "").strip(),
        }

    def _normalize_failure_category(self, error: Exception) -> str:
        message = str(error or "").strip().lower()
        if not message:
            return "unknown"

        if any(token in message for token in ("not authorized", "permission denied", "权限不足", "无权限")):
            return "permission_denied"
        if any(token in message for token in ("api key", "api secret", "signature", "sign", "authentication", "passphrase", "invalid key", "invalid api", "签名", "密钥")):
            return "api_auth_failed"
        if any(token in message for token in ("restricted ip", "ip whitelist", "whitelist", "白名单", "invalid ip")):
            return "ip_whitelist_blocked"
        if any(
            token in message
            for token in ("timeout", "timed out", "超时", "network error", "connection reset", "econnreset")
        ):
            return "temporary_network"
        if any(token in message for token in ("暂不支持", "not supported", "unsupported", "不支持")):
            return "route_unsupported"
        if any(token in message for token in ("账户类型", "account type", "映射", "mapping")):
            return "account_mapping_invalid"
        if any(
            token in message
            for token in ("withdraw disabled", "withdrawal disabled", "withdraw not allowed", "withdraw is disabled", "提现关闭", "提现被禁用", "提现权限")
        ):
            return "withdraw_disabled"
        if any(token in message for token in ("deposit address", "deposit info", "充值", "to account")):
            return "deposit_info_invalid"
        if any(
            token in message
            for token in ("memo", "tag", "invalid network", "network invalid", "未配置提现网络", "可提现网络", "网络配置", "链路", "网络")
        ):
            return "network_invalid"
        if any(token in message for token in ("address", "uid", "地址")):
            return "address_invalid"
        if any(token in message for token in ("temporarily", "internal error", "system busy", "server error", "exchange error")):
            return "temporary_exchange"
        return "temporary_exchange"

    def _translate_exchange_exception_message(self, error: Exception) -> str:
        return str(error or "").strip() or "交易所返回了未知异常。"


transfer_execution_service = TransferExecutionService()
