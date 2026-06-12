"""Read-side account service logic."""

from __future__ import annotations

from typing import Dict, List

from app.application.services.account_monitor_service import account_monitor_service
from app.application.services.account_transfer_capability_service import AccountTransferCapabilityService
from app.application.services.account_support import (
    AccountBalanceSnapshot,
    AccountDetailResult,
    AccountServiceSupport,
    AutoTransferConfigResult,
    FALLBACK_AVAILABLE_AMOUNTS,
    MANUAL_TRANSFER_UI_NOTICE,
)
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import AccountNotFoundError


class AccountQueryService(AccountServiceSupport):
    def __init__(self) -> None:
        self._transfer_capability_service = AccountTransferCapabilityService()

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
            address_network=str(row.get("network") or ""),
            address_value=str(row.get("address_value") or ""),
            address_memo=str(row.get("memo_tag") or ""),
        )

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
        result: List[Dict[str, str]] = []

        for row in rows:
            transfer_source_summary = self._build_transfer_source_summary(row, rows)
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
                    "transfer_supported": bool(transfer_source_summary["transfer_supported"]),
                    "transfer_option_count": int(transfer_source_summary["transfer_option_count"]),
                    "transfer_block_reason": str(transfer_source_summary["transfer_block_reason"]),
                    "transfer_action_hint": str(transfer_source_summary["transfer_action_hint"]),
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
        result: List[Dict[str, str]] = []

        for row, available_value, available, funding_ratio_percent in available_rows:
            exchange = str(row.get("exchange") or "")
            if funding_ratio_percent > 0:
                ratio = funding_ratio_percent / 100
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
                    "transfer_supported": bool(row.get("transfer_supported")),
                    "transfer_option_count": int(row.get("transfer_option_count") or 0),
                    "transfer_block_reason": str(row.get("transfer_block_reason") or ""),
                    "transfer_action_hint": str(row.get("transfer_action_hint") or ""),
                    "updated_at": str(row.get("updated_at") or "--"),
                }
            )

        return result

    def build_summary_cards(
        self,
        account_rows: List[Dict[str, str]],
        balance_rows: List[Dict[str, str]],
        *,
        is_auto_transfer_enabled: bool,
    ) -> List[Dict[str, str]]:
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

    def build_transfer_options_for_user(self, from_account_id: int, user_id: int) -> Dict[str, object]:
        rows = account_repository.list_accounts_with_address_by_user_id(user_id)
        from_account = next((row for row in rows if int(row["id"]) == int(from_account_id)), None)
        if from_account is None:
            raise AccountNotFoundError("转出账户不存在，或你无权操作该账户。")

        transfer_source_summary = self._build_transfer_source_summary(from_account, rows)
        options: List[Dict[str, str]] = []
        blocked_count = 0

        for row in rows:
            if int(row["id"]) == int(from_account_id):
                continue

            capability = self._transfer_capability_service.build_transfer_capability(from_account, row)
            if not capability["supported"]:
                blocked_count += 1
                continue

            options.append(
                {
                    "id": str(row["id"]),
                    "name": self._sanitize_account_name(str(row["account_name"])),
                    "exchange": self._exchange_label(str(row["exchange_code"])),
                    "market_type": self._market_label(str(row["market_type"])),
                    "mode": str(capability["mode"] or ""),
                    "mode_label": self._transfer_mode_label(str(capability["mode"] or "")),
                }
            )

        return {
            "from_account_id": str(from_account["id"]),
            "from_account_name": self._sanitize_account_name(str(from_account["account_name"])),
            "options": options,
            "option_count": len(options),
            "blocked_count": blocked_count,
            "notice": MANUAL_TRANSFER_UI_NOTICE if options else str(transfer_source_summary["transfer_action_hint"]),
        }

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

    def _transfer_mode_label(self, mode: str) -> str:
        return {
            "same_exchange_internal": "同交易所内部调拨",
            "cross_exchange_withdraw": "跨交易所真实调拨",
        }.get(mode, "真实调拨")

    def _build_transfer_source_summary(self, source_row: Dict[str, object], all_rows: List[Dict[str, object]]) -> Dict[str, object]:
        supported_count = 0
        first_block_reason = ""

        for row in all_rows:
            if int(row["id"]) == int(source_row["id"]):
                continue

            capability = self._transfer_capability_service.build_transfer_capability(source_row, row)
            if capability["supported"]:
                supported_count += 1
                continue

            if not first_block_reason and capability["reason"]:
                first_block_reason = str(capability["reason"])

        if supported_count > 0:
            return {
                "transfer_supported": True,
                "transfer_option_count": supported_count,
                "transfer_block_reason": "",
                "transfer_action_hint": f"当前可真实调拨到 {supported_count} 个目标账户。",
            }

        if len(all_rows) <= 1:
            block_reason = "当前仅有 1 个账户，暂无可真实执行的调拨目标。"
        else:
            block_reason = first_block_reason or "当前没有可真实执行的调拨目标。"

        return {
            "transfer_supported": False,
            "transfer_option_count": 0,
            "transfer_block_reason": block_reason,
            "transfer_action_hint": block_reason,
        }
