"""Capability checks for real account transfer execution."""

from __future__ import annotations

from typing import Any, Dict

from app.application.services.account_support import REAL_TRANSFER_EXECUTION_SUPPORTED_EXCHANGES
from app.shared.exceptions import AccountValidationError


class AccountTransferCapabilityService:
    """Single source of truth for what transfer routes can execute for real."""

    def build_transfer_capability(self, from_account: Dict[str, Any], to_account: Dict[str, Any]) -> Dict[str, Any]:
        from_exchange = str(from_account.get("exchange_code") or "").strip().lower()
        to_exchange = str(to_account.get("exchange_code") or "").strip().lower()
        from_market_type = str(from_account.get("market_type") or "").strip().lower()
        to_market_type = str(to_account.get("market_type") or "").strip().lower()
        same_exchange = from_exchange == to_exchange
        same_master_account = self._is_same_master_account(from_account, to_account)

        supported = False
        reason = ""
        mode = ""

        if from_exchange not in REAL_TRANSFER_EXECUTION_SUPPORTED_EXCHANGES:
            reason = f"当前暂不支持 {from_exchange or '--'} 的真实调拨执行。"
        elif to_exchange not in REAL_TRANSFER_EXECUTION_SUPPORTED_EXCHANGES:
            reason = f"当前暂不支持 {to_exchange or '--'} 的真实调拨执行。"
        elif same_exchange and same_master_account:
            if from_exchange in {"binance", "okx"}:
                supported = True
                mode = "same_exchange_internal"
            else:
                reason = f"当前暂不支持 {from_exchange} 的交易所内真实调拨。"
        else:
            if not self._is_cross_exchange_route_supported(from_exchange, to_exchange):
                reason = f"当前暂不支持 {from_exchange} -> {to_exchange} 的跨交易所真实调拨。"
            elif not self._has_valid_cross_exchange_target(to_account):
                reason = "目标账户未配置可用于真实跨交易所调拨的地址与网络。"
            else:
                supported = True
                mode = "cross_exchange_withdraw"

        return {
            "supported": supported,
            "mode": mode,
            "reason": reason,
            "same_exchange": same_exchange,
            "same_master_account": same_master_account,
            "from_exchange": from_exchange,
            "to_exchange": to_exchange,
            "from_market_type": from_market_type,
            "to_market_type": to_market_type,
        }

    def ensure_transfer_supported(self, from_account: Dict[str, Any], to_account: Dict[str, Any]) -> Dict[str, Any]:
        capability = self.build_transfer_capability(from_account, to_account)
        if not capability["supported"]:
            raise AccountValidationError(str(capability["reason"] or "当前调拨路径不支持真实执行。"))
        return capability

    def _is_same_master_account(self, from_account: Dict[str, Any], to_account: Dict[str, Any]) -> bool:
        return (
            str(from_account.get("api_key") or "") == str(to_account.get("api_key") or "")
            and str(from_account.get("api_secret") or "") == str(to_account.get("api_secret") or "")
            and str(from_account.get("api_passphrase") or "") == str(to_account.get("api_passphrase") or "")
        )

    def _is_cross_exchange_route_supported(self, from_exchange: str, to_exchange: str) -> bool:
        return (
            from_exchange in REAL_TRANSFER_EXECUTION_SUPPORTED_EXCHANGES
            and to_exchange in REAL_TRANSFER_EXECUTION_SUPPORTED_EXCHANGES
        )

    def _has_valid_cross_exchange_target(self, to_account: Dict[str, Any]) -> bool:
        network = str(to_account.get("network") or "").strip().lower()
        address = str(to_account.get("address_value") or "").strip()
        return bool(address and network and network != "internal")
