"""Runtime guard for suppressing repeated auto-transfer submissions after config errors."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.infrastructure.cache import redis_runtime_support
from app.infrastructure.persistence.account_repository import account_repository


AUTO_TRANSFER_BLOCK_HASH_KEY = "auto-transfer:block:users"


class AutoTransferRuntimeGuardService:
    def build_config_version(self, user_id: int) -> str:
        return self._build_user_config_version(user_id)

    def is_blocked(self, user_id: int) -> bool:
        payload = self._read_payload(user_id)
        if not isinstance(payload, dict):
            return False

        current_version = self._build_user_config_version(user_id)
        blocked_version = str(payload.get("config_version") or "").strip()
        if blocked_version and blocked_version == current_version:
            return True

        self.clear(user_id)
        return False

    def mark_config_error(self, *, user_id: int, reason: str) -> None:
        payload = {
            "user_id": int(user_id),
            "reason": str(reason or "").strip(),
            "config_version": self._build_user_config_version(user_id),
            "blocked_at": datetime.now(),
        }
        ttl_seconds = 30 * 24 * 60 * 60
        redis_runtime_support.set_hash_field_json(
            AUTO_TRANSFER_BLOCK_HASH_KEY,
            self._field(user_id),
            payload,
            ttl_seconds=ttl_seconds,
        )
        redis_runtime_support.set_json(self._key(user_id), payload, ttl_seconds=ttl_seconds)

    def clear(self, user_id: int) -> None:
        redis_runtime_support.delete_hash_field(AUTO_TRANSFER_BLOCK_HASH_KEY, self._field(user_id))
        redis_runtime_support.delete(self._key(user_id))

    def _key(self, user_id: int) -> str:
        return f"auto-transfer:block:user:{int(user_id)}"

    def _field(self, user_id: int) -> str:
        return f"user:{int(user_id)}"

    def _read_payload(self, user_id: int) -> Dict[str, Any] | None:
        payload = redis_runtime_support.get_hash_field_json(AUTO_TRANSFER_BLOCK_HASH_KEY, self._field(user_id))
        if isinstance(payload, dict):
            return payload
        payload = redis_runtime_support.get_json(self._key(user_id))
        if isinstance(payload, dict):
            return payload
        return None

    def _build_user_config_version(self, user_id: int) -> str:
        config_row = account_repository.get_auto_transfer_config_by_user_id(user_id) or {}
        account_rows = account_repository.list_active_accounts_with_address_by_user_id(user_id)

        account_parts: List[str] = []
        for row in sorted(account_rows, key=lambda item: int(item.get("id") or 0)):
            account_parts.append(
                ":".join(
                    [
                        str(int(row.get("id") or 0)),
                        self._format_dt(row.get("updated_at")),
                        self._format_dt(row.get("address_updated_at")),
                        str(row.get("exchange_code") or ""),
                        str(row.get("market_type") or ""),
                    ]
                )
            )

        return "|".join(
            [
                f"cfg:{self._format_dt(config_row.get('updated_at'))}:{int(bool(config_row.get('is_enabled')))}:{config_row.get('trigger_ratio') or 0}",
                f"accounts:{';'.join(account_parts)}",
            ]
        )

    def _format_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return ""


auto_transfer_runtime_guard_service = AutoTransferRuntimeGuardService()
