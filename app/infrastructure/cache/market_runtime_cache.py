"""In-memory runtime caches for public market data and user opportunity rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Dict, List, Optional, Tuple


TickerCacheKey = Tuple[str, str, str]
FundingRateCacheKey = Tuple[str, str]


@dataclass(frozen=True)
class TickerCacheItem:
    exchange_code: str
    market_type: str
    symbol: str
    last_price: float
    bid_price: float
    ask_price: float
    quote_volume: float
    synced_at: datetime | None


@dataclass(frozen=True)
class FundingRateCacheItem:
    exchange_code: str
    symbol: str
    funding_rate_percent: float
    next_funding_at: datetime | None
    synced_at: datetime | None


class MarketRuntimeCache:
    def __init__(self) -> None:
        self._tickers: Dict[TickerCacheKey, TickerCacheItem] = {}
        self._funding_rates: Dict[FundingRateCacheKey, FundingRateCacheItem] = {}
        self._funding_rows_by_user: Dict[int, List[dict]] = {}
        self._spread_rows_by_user: Dict[int, List[dict]] = {}
        self._lock = RLock()

    def set_ticker(self, item: TickerCacheItem) -> None:
        with self._lock:
            self._tickers[(item.exchange_code, item.market_type, item.symbol)] = item

    def get_ticker(self, exchange_code: str, market_type: str, symbol: str) -> Optional[TickerCacheItem]:
        with self._lock:
            return self._tickers.get((exchange_code, market_type, symbol))

    def list_tickers(self) -> List[TickerCacheItem]:
        with self._lock:
            return list(self._tickers.values())

    def set_funding_rate(self, item: FundingRateCacheItem) -> None:
        with self._lock:
            self._funding_rates[(item.exchange_code, item.symbol)] = item

    def get_funding_rate(self, exchange_code: str, symbol: str) -> Optional[FundingRateCacheItem]:
        with self._lock:
            return self._funding_rates.get((exchange_code, symbol))

    def set_user_rows(self, channel: str, user_id: int, rows: List[dict]) -> None:
        with self._lock:
            if channel == "funding":
                self._funding_rows_by_user[user_id] = list(rows)
                return
            if channel == "spread":
                self._spread_rows_by_user[user_id] = list(rows)

    def get_user_rows(self, channel: str, user_id: int) -> List[dict]:
        with self._lock:
            if channel == "funding":
                return list(self._funding_rows_by_user.get(user_id, []))
            if channel == "spread":
                return list(self._spread_rows_by_user.get(user_id, []))
            return []

    def clear_user_rows(self, channel: str, user_id: int) -> None:
        with self._lock:
            if channel == "funding":
                self._funding_rows_by_user.pop(user_id, None)
                return
            if channel == "spread":
                self._spread_rows_by_user.pop(user_id, None)

    def list_user_ids(self, channel: str) -> List[int]:
        with self._lock:
            if channel == "funding":
                return list(self._funding_rows_by_user.keys())
            if channel == "spread":
                return list(self._spread_rows_by_user.keys())
            return []


market_runtime_cache = MarketRuntimeCache()
