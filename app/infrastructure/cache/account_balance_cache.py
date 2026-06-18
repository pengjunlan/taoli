"""Redis-backed cache for account balance snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from app.infrastructure.cache.redis_runtime_support import redis_runtime_support

ACCOUNT_BALANCE_TTL_SECONDS = 10 * 60


@dataclass(frozen=True)
class AccountBalanceCacheItem:
    account_id: int
    amount: float = 0.0
    user_id: int = 0
    exchange_code: str = ""
    market_type: str = ""
    frozen_amount: float = 0.0
    total_amount: float = 0.0
    synced_at: datetime | None = None


class AccountBalanceCache:
    def initialize(self) -> None:
        redis_runtime_support.initialize()

    def prime(self, items: Iterable[AccountBalanceCacheItem]) -> None:
        for item in items:
            self._write_redis(item)

    def get(self, account_id: int, *, user_id: int | None = None) -> Optional[AccountBalanceCacheItem]:
        resolved_user_id = int(user_id or 0)
        return self._read_redis(account_id, user_id=resolved_user_id)

    def set(self, item: AccountBalanceCacheItem) -> None:
        self._write_redis(item)

    def delete(self, account_id: int, *, user_id: int | None = None) -> None:
        resolved_user_id = int(user_id or 0)
        if resolved_user_id > 0:
            redis_runtime_support.delete(self._redis_key(account_id, user_id=resolved_user_id))

    def _redis_key(self, account_id: int, *, user_id: int) -> str:
        return f"account-balance:user:{int(user_id)}:account:{int(account_id)}"

    def _serialize_item(self, item: AccountBalanceCacheItem) -> Dict[str, object]:
        return {
            "user_id": int(item.user_id or 0),
            "account_id": int(item.account_id),
            "exchange_code": str(item.exchange_code or ""),
            "market_type": str(item.market_type or ""),
            "available_amount": float(item.amount or 0),
            "amount": float(item.amount or 0),
            "frozen_amount": float(item.frozen_amount or 0),
            "total_amount": float(item.total_amount or 0),
            "synced_at": item.synced_at,
        }

    def _write_redis(self, item: AccountBalanceCacheItem) -> None:
        if int(item.user_id or 0) <= 0:
            return
        payload = self._serialize_item(item)
        redis_runtime_support.set_json(
            self._redis_key(item.account_id, user_id=int(item.user_id)),
            payload,
            ttl_seconds=ACCOUNT_BALANCE_TTL_SECONDS,
        )

    def _read_redis(self, account_id: int, *, user_id: int) -> Optional[AccountBalanceCacheItem]:
        if user_id <= 0:
            return None
        payload = redis_runtime_support.get_json(self._redis_key(account_id, user_id=user_id))
        if not isinstance(payload, dict):
            return None
        try:
            return AccountBalanceCacheItem(
                account_id=int(payload.get("account_id") or account_id),
                user_id=int(payload.get("user_id") or user_id or 0),
                exchange_code=str(payload.get("exchange_code") or ""),
                market_type=str(payload.get("market_type") or ""),
                amount=float(payload.get("available_amount") or payload.get("amount") or 0),
                frozen_amount=float(payload.get("frozen_amount") or 0),
                total_amount=float(payload.get("total_amount") or 0),
                synced_at=redis_runtime_support.parse_datetime(payload.get("synced_at")),
            )
        except (TypeError, ValueError):
            return None


account_balance_cache = AccountBalanceCache()
