"""Redis-backed runtime cache for strategy decision payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, List

from app.infrastructure.cache.redis_runtime_support import redis_runtime_support

STRATEGY_RUNTIME_TTL_SECONDS = 5 * 60


class StrategyRuntimeCache:
    def initialize(self) -> None:
        redis_runtime_support.initialize()

    def set_user_payload(self, user_id: int, payload: Dict[str, object]) -> None:
        cloned = deepcopy(payload)
        redis_runtime_support.set_json(self._key(user_id), cloned, ttl_seconds=STRATEGY_RUNTIME_TTL_SECONDS)

    def get_user_payload(self, user_id: int) -> Dict[str, object]:
        payload = redis_runtime_support.get_json(self._key(user_id))
        if isinstance(payload, dict):
            return deepcopy(payload)
        return {}

    def clear_user_payload(self, user_id: int) -> None:
        redis_runtime_support.delete(self._key(user_id))

    def list_user_ids(self) -> List[int]:
        result: List[int] = []
        prefix = "strategy-runtime:user:"
        for key, payload in redis_runtime_support.list_json(f"{prefix}*"):
            if not key.startswith(prefix) or not isinstance(payload, dict):
                continue
            try:
                result.append(int(key[len(prefix) :]))
            except ValueError:
                continue
        return sorted(set(result))

    def _key(self, user_id: int) -> str:
        return f"strategy-runtime:user:{int(user_id)}"


strategy_runtime_cache = StrategyRuntimeCache()
