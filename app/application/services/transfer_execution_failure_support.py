"""Failure classification helpers for transfer execution."""

from __future__ import annotations

from typing import Any, Dict

from app.shared.exceptions import ExchangeConnectionError, ExchangeValidationError


class TransferExecutionFailureSupportMixin:
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
        if any(token in message for token in ("timeout", "timed out", "超时", "network error", "connection reset", "econnreset")):
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
