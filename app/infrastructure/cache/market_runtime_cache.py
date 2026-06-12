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


@dataclass(frozen=True)
class OpportunityRowsState:
    channel: str
    user_id: int
    rows: List[dict]
    is_ready: bool
    source: str
    generated_at: datetime | None
    updated_at: datetime | None
    message: str


class MarketRuntimeCache:
    def __init__(self) -> None:
        self._tickers: Dict[TickerCacheKey, TickerCacheItem] = {}
        self._funding_rates: Dict[FundingRateCacheKey, FundingRateCacheItem] = {}
        self._funding_rows_by_user: Dict[int, OpportunityRowsState] = {}
        self._spread_rows_by_user: Dict[int, OpportunityRowsState] = {}
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

    def set_user_rows(
        self,
        channel: str,
        user_id: int,
        rows: List[dict],
        *,
        is_ready: bool = True,
        source: str = "runtime",
        generated_at: datetime | None = None,
        updated_at: datetime | None = None,
        message: str = "",
    ) -> None:
        with self._lock:
            state = OpportunityRowsState(
                channel=channel,
                user_id=user_id,
                rows=list(rows),
                is_ready=is_ready,
                source=source,
                generated_at=generated_at,
                updated_at=updated_at or datetime.now(),
                message=message,
            )
            if channel == "funding":
                self._funding_rows_by_user[user_id] = state
                return
            if channel == "spread":
                self._spread_rows_by_user[user_id] = state

    def get_user_rows(self, channel: str, user_id: int) -> List[dict]:
        state = self.get_user_rows_state(channel, user_id)
        return list(state.rows) if state is not None else []

    def get_user_rows_state(self, channel: str, user_id: int) -> Optional[OpportunityRowsState]:
        with self._lock:
            if channel == "funding":
                state = self._funding_rows_by_user.get(user_id)
                if state is None:
                    return None
                return OpportunityRowsState(
                    channel=state.channel,
                    user_id=state.user_id,
                    rows=list(state.rows),
                    is_ready=state.is_ready,
                    source=state.source,
                    generated_at=state.generated_at,
                    updated_at=state.updated_at,
                    message=state.message,
                )
            if channel == "spread":
                state = self._spread_rows_by_user.get(user_id)
                if state is None:
                    return None
                return OpportunityRowsState(
                    channel=state.channel,
                    user_id=state.user_id,
                    rows=list(state.rows),
                    is_ready=state.is_ready,
                    source=state.source,
                    generated_at=state.generated_at,
                    updated_at=state.updated_at,
                    message=state.message,
                )
            return None

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
