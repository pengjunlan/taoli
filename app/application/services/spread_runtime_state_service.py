"""Runtime state helpers for spread-arbitrage staged execution."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from app.infrastructure.cache import redis_runtime_support


class SpreadRuntimeStateService:
    _KEY_PREFIX = "spread:runtime"

    def get_pair_state(self, *, user_id: int, rule_id: int, pair_key: str) -> Dict[str, Any]:
        payload = redis_runtime_support.get_json(self._key(user_id=user_id, rule_id=rule_id, pair_key=pair_key))
        return dict(payload) if isinstance(payload, dict) else {}

    def set_pair_state(
        self,
        *,
        user_id: int,
        rule_id: int,
        pair_key: str,
        payload: Dict[str, Any],
        ttl_seconds: int = 7 * 24 * 60 * 60,
    ) -> None:
        redis_runtime_support.set_json(
            self._key(user_id=user_id, rule_id=rule_id, pair_key=pair_key),
            payload,
            ttl_seconds=ttl_seconds,
        )

    def patch_pair_state(
        self,
        *,
        user_id: int,
        rule_id: int,
        pair_key: str,
        **updates: Any,
    ) -> Dict[str, Any]:
        current = self.get_pair_state(user_id=user_id, rule_id=rule_id, pair_key=pair_key)
        current.update(updates)
        current["updated_at"] = datetime.now()
        self.set_pair_state(user_id=user_id, rule_id=rule_id, pair_key=pair_key, payload=current)
        return current

    def clear_pair_state(self, *, user_id: int, rule_id: int, pair_key: str) -> None:
        redis_runtime_support.delete(self._key(user_id=user_id, rule_id=rule_id, pair_key=pair_key))

    def _key(self, *, user_id: int, rule_id: int, pair_key: str) -> str:
        return f"{self._KEY_PREFIX}:{int(user_id)}:{int(rule_id)}:{pair_key}"


spread_runtime_state_service = SpreadRuntimeStateService()


__all__ = [
    "SpreadRuntimeStateService",
    "spread_runtime_state_service",
]
