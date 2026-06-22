"""Per-account auto-transfer failure guard with manual unlock."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from app.infrastructure.cache import redis_runtime_support


AUTO_TRANSFER_ACCOUNT_GUARD_PREFIX = "auto-transfer:account-guard:user:"
AUTO_TRANSFER_ACCOUNT_GUARD_TTL_SECONDS = 90 * 24 * 60 * 60
NON_ACCOUNT_GUARD_ERROR_CATEGORIES = {"route_unsupported"}


class AutoTransferAccountGuardService:
    def list_states(self, user_id: int) -> Dict[int, Dict[str, Any]]:
        raw_mapping = redis_runtime_support.get_hash_json(self._key(user_id))
        result: Dict[int, Dict[str, Any]] = {}
        stale_account_ids: list[int] = []
        if not isinstance(raw_mapping, dict):
            return result

        for field, payload in raw_mapping.items():
            try:
                account_id = int(field)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            normalized = self._normalize_payload(payload)
            if not self._should_keep_payload(normalized):
                stale_account_ids.append(account_id)
                continue
            result[account_id] = normalized

        if stale_account_ids:
            self.clear_accounts(user_id, stale_account_ids)
        return result

    def get_state(self, user_id: int, account_id: int) -> Dict[str, Any] | None:
        payload = redis_runtime_support.get_hash_field_json(self._key(user_id), self._field(account_id))
        if not isinstance(payload, dict):
            return None
        normalized = self._normalize_payload(payload)
        if not self._should_keep_payload(normalized):
            self.clear_account(user_id, account_id)
            return None
        return normalized

    def is_frozen(self, user_id: int, account_id: int) -> bool:
        state = self.get_state(user_id, account_id)
        return bool(state and state.get("is_frozen"))

    def record_failure(
        self,
        *,
        user_id: int,
        account_id: int,
        exchange_code: str,
        account_name: str,
        error_category: str,
        error_label: str,
        raw_message: str,
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        existing = self.get_state(user_id, account_id) or {}
        same_category = str(existing.get("error_category") or "") == str(error_category or "")
        consecutive_count = int(existing.get("consecutive_count") or 0) + 1 if same_category else 1
        is_frozen = bool(existing.get("is_frozen")) or consecutive_count >= 2

        payload = {
            "user_id": int(user_id),
            "account_id": int(account_id),
            "exchange_code": str(exchange_code or "").strip().lower(),
            "account_name": str(account_name or "").strip(),
            "error_category": str(error_category or "").strip().lower(),
            "error_label": str(error_label or "账户配置异常").strip(),
            "raw_message": str(raw_message or "").strip(),
            "consecutive_count": consecutive_count,
            "is_frozen": is_frozen,
            "last_error_at": now,
            "frozen_at": str(existing.get("frozen_at") or now) if is_frozen else "",
        }
        redis_runtime_support.set_hash_field_json(
            self._key(user_id),
            self._field(account_id),
            payload,
            ttl_seconds=AUTO_TRANSFER_ACCOUNT_GUARD_TTL_SECONDS,
        )
        return payload

    def clear_account(self, user_id: int, account_id: int) -> None:
        redis_runtime_support.delete_hash_field(self._key(user_id), self._field(account_id))

    def clear_accounts(self, user_id: int, account_ids: list[int]) -> None:
        for account_id in account_ids:
            if int(account_id or 0) > 0:
                self.clear_account(user_id, int(account_id))

    def unlock_account(self, user_id: int, account_id: int) -> None:
        self.clear_account(user_id, account_id)

    def clear_non_frozen_account_by_categories(
        self,
        user_id: int,
        account_id: int,
        categories: set[str] | None = None,
    ) -> bool:
        state = self.get_state(user_id, account_id)
        if not state or bool(state.get("is_frozen")):
            return False

        normalized_categories = {
            str(category or "").strip().lower()
            for category in (categories or set())
            if str(category or "").strip()
        }
        if normalized_categories and str(state.get("error_category") or "") not in normalized_categories:
            return False

        self.clear_account(user_id, account_id)
        return True

    def build_alert_summary(self, user_id: int) -> Dict[str, Any] | None:
        states = [
            state
            for state in self.list_states(user_id).values()
            if int(state.get("account_id") or 0) > 0
        ]
        if not states:
            return None

        primary = max(
            states,
            key=lambda item: (
                1 if bool(item.get("is_frozen")) else 0,
                str(item.get("last_error_at") or ""),
            ),
        )
        account_name = str(primary.get("account_name") or "该账户")
        error_label = str(primary.get("error_label") or "账户配置异常")
        count = int(primary.get("consecutive_count") or 0)
        frozen = bool(primary.get("is_frozen"))
        extra_count = max(len(states) - 1, 0)

        if frozen:
            message = (
                f"{account_name} 已冻结自动调拨：{error_label}（连续 {count} 次）。"
                " 请修正账户配置后手动解冻。"
            )
            level = "negative"
        else:
            message = (
                f"{account_name} 自动调拨执行失败 1 次：{error_label}。"
                " 如果再次出现同类问题，将自动冻结该账户。"
            )
            level = "warning"

        if extra_count > 0:
            message = f"{message} 另有 {extra_count} 条账户告警。"

        return {
            "level": level,
            "message": message,
            "account_id": int(primary.get("account_id") or 0),
            "account_name": account_name,
            "error_label": error_label,
            "raw_message": str(primary.get("raw_message") or "").strip(),
            "is_frozen": frozen,
            "consecutive_count": count,
            "last_error_at": str(primary.get("last_error_at") or ""),
        }

    def _key(self, user_id: int) -> str:
        return f"{AUTO_TRANSFER_ACCOUNT_GUARD_PREFIX}{int(user_id)}"

    def _field(self, account_id: int) -> str:
        return str(int(account_id))

    def _should_keep_payload(self, payload: Dict[str, Any]) -> bool:
        category = str(payload.get("error_category") or "").strip().lower()
        if not category:
            return True
        return category not in NON_ACCOUNT_GUARD_ERROR_CATEGORIES

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "user_id": int(payload.get("user_id") or 0),
            "account_id": int(payload.get("account_id") or 0),
            "exchange_code": str(payload.get("exchange_code") or "").strip().lower(),
            "account_name": str(payload.get("account_name") or "").strip(),
            "error_category": str(payload.get("error_category") or "").strip().lower(),
            "error_label": str(payload.get("error_label") or "账户配置异常").strip(),
            "raw_message": str(payload.get("raw_message") or "").strip(),
            "consecutive_count": int(payload.get("consecutive_count") or 0),
            "is_frozen": bool(payload.get("is_frozen")),
            "last_error_at": str(payload.get("last_error_at") or "").strip(),
            "frozen_at": str(payload.get("frozen_at") or "").strip(),
        }


auto_transfer_account_guard_service = AutoTransferAccountGuardService()
