"""In-memory runtime cache for strategy decision payloads."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Dict, List


class StrategyRuntimeCache:
    def __init__(self) -> None:
        self._payloads_by_user: Dict[int, Dict[str, object]] = {}
        self._lock = RLock()

    def set_user_payload(self, user_id: int, payload: Dict[str, object]) -> None:
        with self._lock:
            self._payloads_by_user[user_id] = deepcopy(payload)

    def get_user_payload(self, user_id: int) -> Dict[str, object]:
        with self._lock:
            payload = self._payloads_by_user.get(user_id)
            if payload is None:
                return {}
            return deepcopy(payload)

    def clear_user_payload(self, user_id: int) -> None:
        with self._lock:
            self._payloads_by_user.pop(user_id, None)

    def list_user_ids(self) -> List[int]:
        with self._lock:
            return list(self._payloads_by_user.keys())


strategy_runtime_cache = StrategyRuntimeCache()
