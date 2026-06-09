"""In-memory cache for account available balances."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class AccountBalanceCacheItem:
    account_id: int
    amount: float
    synced_at: datetime | None


class AccountBalanceCache:
    def __init__(self) -> None:
        self._items: Dict[int, AccountBalanceCacheItem] = {}
        self._lock = RLock()

    def prime(self, items: Iterable[AccountBalanceCacheItem]) -> None:
        with self._lock:
            self._items = {item.account_id: item for item in items}

    def get(self, account_id: int) -> Optional[AccountBalanceCacheItem]:
        with self._lock:
            return self._items.get(account_id)

    def set(self, item: AccountBalanceCacheItem) -> None:
        with self._lock:
            self._items[item.account_id] = item

    def delete(self, account_id: int) -> None:
        with self._lock:
            self._items.pop(account_id, None)


account_balance_cache = AccountBalanceCache()
