"""Shared account service support types and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Dict


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
    "plasma": "Plasma",
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

# This explicitly documents the current implementation truth:
# manual transfer records are routed into the worker execution pipeline and
# are expected to execute against real exchange APIs.
MANUAL_TRANSFER_EXECUTION_MODE = "worker_enabled"
MANUAL_TRANSFER_EXECUTION_RESULT_HINT = "手动调拨任务已创建，后台将立即进入真实执行流程。"
MANUAL_TRANSFER_UI_NOTICE = "手动调拨可直接提交，后台会按记录尝试执行，成功或失败以执行结果为准。"

REAL_TRANSFER_EXECUTION_SUPPORTED_EXCHANGES = {"binance", "okx"}


@dataclass(frozen=True)
class AccountCreateResult:
    account: object


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
    maker_fee_rate: float
    taker_fee_rate: float
    fee_rate_synced_at: datetime | None
    address_network: str
    address_value: str
    address_memo: str


@dataclass(frozen=True)
class TransferCreateResult:
    transfer_record: object


@dataclass(frozen=True)
class AutoTransferConfigResult:
    is_enabled: bool
    trigger_ratio: float


@dataclass(frozen=True)
class AutoTransferExecutionResult:
    transfer_record: object


@dataclass(frozen=True)
class AccountBalanceSnapshot:
    available_value: float
    available_display: str
    is_real: bool


class AccountServiceSupport:
    """Reusable helpers shared by split account service modules."""

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

    def _build_account_name(self, exchange_code: str, market_type: str) -> str:
        return f"{self._exchange_label(exchange_code)} {self._market_label(market_type)}账户"

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
        from app.shared.exceptions import AccountValidationError

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
            "pending": "待执行",
            "created": "已创建",
            "processing": "处理中",
            "pending_execute": "待执行",
            "executing": "处理中",
            "processed": "已处理",
            "success": "已完成",
            "failed": "失败",
            "ignored": "已忽略",
        }.get(value, "待执行")

    def _transfer_status_tone(self, value: str) -> str:
        return {
            "pending": "brand",
            "created": "brand",
            "processing": "warning",
            "pending_execute": "brand",
            "executing": "warning",
            "processed": "neutral",
            "success": "positive",
            "failed": "negative",
            "ignored": "neutral",
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
