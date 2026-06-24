"""Shared account service support types and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Dict, Mapping

from app.application.services.exchange_transfer_adapters import normalize_network_code


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
    "xpl": "Plasma",
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

REAL_TRANSFER_EXECUTION_SUPPORTED_EXCHANGES = {"binance", "okx", "gate", "bitget"}
TRANSFER_EXECUTION_SNAPSHOT_PAYLOAD_KEY = "_transfer_snapshot"
TRANSFER_EXECUTION_SNAPSHOT_CONTEXT_FIELDS = (
    "from_market_type",
    "from_exchange_code",
    "from_api_key",
    "from_api_secret",
    "from_api_passphrase",
    "to_market_type",
    "to_exchange_code",
    "to_api_key",
    "to_api_secret",
    "to_api_passphrase",
    "to_network",
    "to_address_value",
    "to_memo_tag",
)
TRANSFER_CHECKPOINT_SAME_EXCHANGE_COMPLETED = "same_exchange_completed"
TRANSFER_CHECKPOINT_SOURCE_INTERNAL_PREPARED = "source_internal_prepared"
TRANSFER_CHECKPOINT_WITHDRAW_SUBMITTED = "withdraw_submitted"
TRANSFER_CHECKPOINT_AWAITING_TARGET_CREDIT = "awaiting_target_credit"
TRANSFER_CHECKPOINT_TARGET_CREDIT_CONFIRMED = "target_credit_confirmed"
TRANSFER_CHECKPOINT_AWAITING_TARGET_INTERNAL_TRANSFER = "awaiting_target_internal_transfer"
TRANSFER_CHECKPOINT_TARGET_INTERNAL_TRANSFERRED = "target_internal_transferred"


def build_transfer_execution_snapshot(
    from_account: Mapping[str, Any],
    to_account: Mapping[str, Any],
) -> Dict[str, str]:
    return {
        "from_market_type": str(from_account.get("market_type") or "").strip().lower(),
        "from_exchange_code": str(from_account.get("exchange_code") or "").strip().lower(),
        "from_api_key": str(from_account.get("api_key") or "").strip(),
        "from_api_secret": str(from_account.get("api_secret") or "").strip(),
        "from_api_passphrase": str(from_account.get("api_passphrase") or "").strip(),
        "to_market_type": str(to_account.get("market_type") or "").strip().lower(),
        "to_exchange_code": str(to_account.get("exchange_code") or "").strip().lower(),
        "to_api_key": str(to_account.get("api_key") or "").strip(),
        "to_api_secret": str(to_account.get("api_secret") or "").strip(),
        "to_api_passphrase": str(to_account.get("api_passphrase") or "").strip(),
        "to_network": normalize_network_code(str(to_account.get("network") or "").strip()),
        "to_address_value": str(to_account.get("address_value") or "").strip(),
        "to_memo_tag": str(to_account.get("memo_tag") or "").strip(),
    }


def build_transfer_execution_payload(snapshot: Mapping[str, Any]) -> str:
    payload = {
        TRANSFER_EXECUTION_SNAPSHOT_PAYLOAD_KEY: {
            key: str(value or "").strip() if isinstance(value, str) else value
            for key, value in dict(snapshot).items()
        }
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def build_transfer_config_fingerprint(snapshot: Mapping[str, Any]) -> str:
    serialized = json.dumps(dict(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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
            "address_network": self._normalize_address_network(address_network),
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
        if address_network and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", address_network):
            raise AccountValidationError("网络类型格式不正确，请选择有效的网络选项。")

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
        text = str(network_code or "").strip()
        if not text:
            return ""
        normalized = text.lower()
        if normalized in NETWORK_LABELS:
            return NETWORK_LABELS[normalized]
        return text.replace("_", " ").replace("-", " ")

    def _normalize_address_network(self, network_code: str) -> str:
        text = str(network_code or "").strip()
        if not text:
            return ""
        return normalize_network_code(text)

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
            "created": "待执行",
            "processing": "执行中",
            "pending_execute": "待执行",
            "executing": "执行中",
            "source_internal_prepared": "执行中",
            "withdraw_submitted": "执行中",
            "awaiting_target_credit": "执行中",
            "awaiting_target_internal_transfer": "执行中",
            "processed": "执行中",
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
            "source_internal_prepared": "warning",
            "withdraw_submitted": "warning",
            "awaiting_target_credit": "warning",
            "awaiting_target_internal_transfer": "warning",
            "processed": "neutral",
            "success": "positive",
            "failed": "negative",
            "ignored": "neutral",
        }.get(value, "brand")

    def _build_transfer_display(self, row: Mapping[str, Any]) -> Dict[str, str]:
        status_code = self._resolve_transfer_display_status_code(row)
        return {
            "status": self._transfer_status_label(status_code),
            "status_tone": self._transfer_status_tone(status_code),
            "result": self._resolve_transfer_display_result(row, status_code=status_code),
        }

    def _resolve_transfer_display_status_code(self, row: Mapping[str, Any]) -> str:
        status = str(row.get("status") or "").strip().lower()
        execute_status = str(row.get("execute_status") or "").strip().lower()
        result_status = str(row.get("result_status") or "").strip().lower()
        checkpoint = str(row.get("execution_checkpoint") or "").strip().lower()
        payload = self._load_transfer_execution_payload(row.get("execution_payload"))
        requires_target_account_alignment = self._read_transfer_payload_bool(
            payload,
            "_requires_target_account_alignment",
        )

        if result_status == "ignored" or status == "ignored":
            return "ignored"
        if result_status == "failed" or status == "failed":
            return "failed"
        if checkpoint in {
            TRANSFER_CHECKPOINT_SAME_EXCHANGE_COMPLETED,
            TRANSFER_CHECKPOINT_TARGET_INTERNAL_TRANSFERRED,
        }:
            return "success"
        if checkpoint in {
            TRANSFER_CHECKPOINT_TARGET_CREDIT_CONFIRMED,
            TRANSFER_CHECKPOINT_AWAITING_TARGET_INTERNAL_TRANSFER,
        }:
            if (
                checkpoint == TRANSFER_CHECKPOINT_TARGET_CREDIT_CONFIRMED
                and requires_target_account_alignment is False
            ):
                return "success"
            return "awaiting_target_internal_transfer"
        if checkpoint == TRANSFER_CHECKPOINT_AWAITING_TARGET_CREDIT:
            return "awaiting_target_credit"
        if checkpoint == TRANSFER_CHECKPOINT_WITHDRAW_SUBMITTED:
            if "_target_credit_balance_before" in payload:
                return "awaiting_target_credit"
            return "withdraw_submitted"
        if checkpoint == TRANSFER_CHECKPOINT_SOURCE_INTERNAL_PREPARED:
            return "source_internal_prepared"
        if result_status == "success" or status == "success":
            return "success"
        if execute_status == "executing" or status == "processing":
            return "executing"
        if status == "created":
            return "created"
        if execute_status == "pending_execute" or status == "pending":
            return "pending"
        if execute_status == "processed":
            return "processed"
        return execute_status or status or "pending"

    def _resolve_transfer_display_result(
        self,
        row: Mapping[str, Any],
        *,
        status_code: str | None = None,
    ) -> str:
        resolved_status = status_code or self._resolve_transfer_display_status_code(row)
        checkpoint = str(row.get("execution_checkpoint") or "").strip().lower()
        failure_type = str(row.get("failure_type") or "").strip().lower()
        failure_reason = str(row.get("failure_reason") or "").strip()
        raw_result = str(row.get("result") or "").strip()
        reference = self._normalize_transfer_reference(row.get("execution_reference"))
        payload = self._load_transfer_execution_payload(row.get("execution_payload"))
        credited_amount = self._read_transfer_payload_amount(payload, "_target_credit_amount")
        transferred_amount = self._read_transfer_payload_amount(payload, "_target_internal_transfer_amount")
        requires_target_account_alignment = self._read_transfer_payload_bool(
            payload,
            "_requires_target_account_alignment",
        )
        hint = self._extract_transfer_runtime_hint(raw_result)

        if resolved_status == "ignored":
            return raw_result or "该记录已忽略。"

        if resolved_status == "failed":
            reason = failure_reason or raw_result or "调拨执行失败。"
            return f"{self._transfer_failure_type_label(failure_type)}：{reason}"

        if checkpoint == TRANSFER_CHECKPOINT_SAME_EXCHANGE_COMPLETED or (
            resolved_status == "success" and checkpoint == TRANSFER_CHECKPOINT_SAME_EXCHANGE_COMPLETED
        ):
            return self._compose_transfer_result(
                [
                    "任务已创建",
                    "已转入目标业务账户",
                    "已完成",
                    self._build_transfer_reference_segment(reference, label="内部划转记录号"),
                ],
                hint="",
            )

        if resolved_status == "source_internal_prepared":
            return self._compose_transfer_result(
                [
                    "任务已创建",
                    "源账户资金已归集到提现账户",
                ],
                hint=hint,
            )

        if resolved_status == "withdraw_submitted":
            return self._compose_transfer_result(
                [
                    "任务已创建",
                    "已提交出金申请",
                    self._build_transfer_reference_segment(reference),
                ],
                hint=hint,
            )

        if resolved_status == "awaiting_target_credit":
            return self._compose_transfer_result(
                [
                    "任务已创建",
                    "已提交出金申请",
                    self._build_transfer_reference_segment(reference),
                    "等待目标到账",
                ],
                hint=hint,
            )

        if resolved_status == "awaiting_target_internal_transfer":
            return self._compose_transfer_result(
                [
                    "任务已创建",
                    "已提交出金申请",
                    self._build_transfer_reference_segment(reference),
                    self._build_transfer_progress_segment("目标已到账", "已确认", credited_amount),
                    "已转入目标业务账户：处理中",
                ],
                hint=hint,
            )

        if resolved_status == "success":
            if checkpoint == TRANSFER_CHECKPOINT_TARGET_INTERNAL_TRANSFERRED or transferred_amount is not None:
                return self._compose_transfer_result(
                    [
                        "任务已创建",
                        "已提交出金申请",
                        self._build_transfer_reference_segment(reference),
                        self._build_transfer_progress_segment("目标已到账", "已确认", credited_amount),
                        self._build_transfer_progress_segment("已转入目标业务账户", "已完成", transferred_amount),
                        "已完成",
                    ],
                    hint="",
                )
            if (
                checkpoint == TRANSFER_CHECKPOINT_TARGET_CREDIT_CONFIRMED
                and requires_target_account_alignment is False
            ):
                return self._compose_transfer_result(
                    [
                        "任务已创建",
                        "已提交出金申请",
                        self._build_transfer_reference_segment(reference),
                        self._build_transfer_progress_segment("目标已到账", "已确认", credited_amount),
                        "已完成",
                    ],
                    hint="",
                )

            return self._compose_transfer_result(
                [
                    "任务已创建",
                    "已完成",
                    self._build_transfer_reference_segment(reference),
                ],
                hint=hint,
            )

        if resolved_status == "executing":
            return self._compose_transfer_result(
                [
                    "任务已创建",
                    "后台正在执行调拨",
                ],
                hint=hint,
            )

        if resolved_status in {"pending", "created"}:
            return "任务已创建"

        return raw_result or "--"

    def _transfer_failure_type_label(self, value: str) -> str:
        return {
            "config": "失败：配置问题",
            "temporary": "失败：临时问题",
            "business": "失败：业务条件问题",
        }.get(value, "失败")

    def _load_transfer_execution_payload(self, raw_payload: Any) -> Dict[str, Any]:
        if raw_payload is None:
            return {}
        text = str(raw_payload).strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _read_transfer_payload_amount(self, payload: Mapping[str, Any], key: str) -> float | None:
        value = payload.get(key)
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        return amount if amount > 0 else None

    def _read_transfer_payload_bool(self, payload: Mapping[str, Any], key: str) -> bool | None:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        return None

    def _format_asset_amount(self, value: float) -> str:
        text = f"{float(value):,.8f}".rstrip("0").rstrip(".")
        return f"{text} USDT"

    def _normalize_transfer_reference(self, value: Any) -> str:
        reference = str(value or "").strip()
        if not reference or reference == "--":
            return ""
        return reference

    def _build_transfer_reference_segment(self, reference: str, *, label: str = "出金记录号") -> str:
        if not reference:
            return ""
        return f"{label}：{reference}"

    def _build_transfer_progress_segment(self, label: str, progress: str, amount: float | None = None) -> str:
        if amount is None:
            return f"{label}：{progress}"
        return f"{label}：{progress}（{self._format_asset_amount(amount)}）"

    def _compose_transfer_result(self, parts: list[str], *, hint: str) -> str:
        cleaned_parts = [str(part).strip() for part in parts if str(part).strip()]
        if hint:
            cleaned_parts.append(f"当前提示：{hint}")
        return "；".join(cleaned_parts) if cleaned_parts else "--"

    def _extract_transfer_runtime_hint(self, result_text: str) -> str:
        text = str(result_text or "").strip()
        if not text:
            return ""
        generic_texts = {
            "后台线程已接单，开始执行调拨。",
            "手动调拨任务已创建，后台将立即进入真实执行流程。",
        }
        if text in generic_texts:
            return ""
        if text.startswith("跨交易所调拨已提交，出金记录号 "):
            return ""
        if text.startswith("跨交易所调拨已完成，出金记录号 "):
            return ""
        marker = "当前提示："
        if marker in text:
            return text.split(marker, 1)[1].strip()
        return text

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
