"""Redis-backed runtime caches for market data and user opportunity rows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, Optional

from app.infrastructure.cache.redis_runtime_support import redis_runtime_support

MARKET_TICKER_TTL_SECONDS = 120 * 60
MARKET_FUNDING_TTL_SECONDS = 120 * 60
OPPORTUNITY_ROWS_TTL_SECONDS = 5 * 60


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
    settlement_interval_hours: float | None = None


@dataclass(frozen=True)
class OpportunityRowsState:
    channel: str
    rows: List[dict]
    is_ready: bool
    source: str
    generated_at: datetime | None
    updated_at: datetime | None
    message: str
    user_id: int | None = None


@dataclass(frozen=True)
class OpportunityRowRuntimeItem:
    channel: str
    row_key: str
    row: dict
    is_ready: bool
    source: str
    generated_at: datetime | None
    updated_at: datetime | None
    message: str
    user_id: int | None = None


class MarketRuntimeCache:
    def initialize(self) -> None:
        redis_runtime_support.initialize()

    def set_ticker(self, item: TickerCacheItem) -> None:
        redis_runtime_support.set_json(
            self._ticker_key(item.exchange_code, item.market_type, item.symbol),
            asdict(item),
            ttl_seconds=MARKET_TICKER_TTL_SECONDS,
        )

    def get_ticker(self, exchange_code: str, market_type: str, symbol: str) -> Optional[TickerCacheItem]:
        return self._read_ticker_redis(exchange_code, market_type, symbol)

    def list_tickers(self) -> List[TickerCacheItem]:
        result: List[TickerCacheItem] = []
        for _, payload in redis_runtime_support.list_json("market:ticker:*"):
            if not isinstance(payload, dict):
                continue
            item = self._build_ticker_item(payload)
            if item is not None:
                result.append(item)
        return result

    def set_funding_rate(self, item: FundingRateCacheItem) -> None:
        redis_runtime_support.set_json(
            self._funding_key(item.exchange_code, item.symbol),
            asdict(item),
            ttl_seconds=MARKET_FUNDING_TTL_SECONDS,
        )

    def get_funding_rate(self, exchange_code: str, symbol: str) -> Optional[FundingRateCacheItem]:
        return self._read_funding_redis(exchange_code, symbol)

    def set_public_rows(
        self,
        channel: str,
        rows: List[dict],
        *,
        is_ready: bool = True,
        source: str = "runtime",
        generated_at: datetime | None = None,
        updated_at: datetime | None = None,
        message: str = "",
    ) -> None:
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        self._sync_public_rows_hash(
            channel=channel,
            rows=normalized_rows,
            is_ready=is_ready,
            source=source,
            generated_at=generated_at,
            updated_at=updated_at,
            message=message,
        )

    def get_public_rows(self, channel: str) -> List[dict]:
        state = self.get_public_rows_state(channel)
        return list(state.rows) if state is not None else []

    def get_public_rows_state(self, channel: str) -> Optional[OpportunityRowsState]:
        return self._read_public_rows_state(channel)

    def clear_public_rows(self, channel: str) -> None:
        redis_runtime_support.delete(self._public_rows_key(channel))

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
        state = OpportunityRowsState(
            channel=channel,
            rows=list(rows),
            is_ready=is_ready,
            source=source,
            generated_at=generated_at,
            updated_at=updated_at or datetime.now(),
            message=message,
            user_id=int(user_id),
        )
        redis_runtime_support.set_json(
            self._user_rows_key(channel, user_id),
            asdict(state),
            ttl_seconds=OPPORTUNITY_ROWS_TTL_SECONDS,
        )

    def get_user_rows(self, channel: str, user_id: int) -> List[dict]:
        state = self.get_user_rows_state(channel, user_id)
        return list(state.rows) if state is not None else []

    def get_user_rows_state(self, channel: str, user_id: int) -> Optional[OpportunityRowsState]:
        return self._read_user_rows_redis(channel, user_id)

    def clear_user_rows(self, channel: str, user_id: int) -> None:
        redis_runtime_support.delete(self._user_rows_key(channel, user_id))

    def list_user_ids(self, channel: str) -> List[int]:
        result: List[int] = []
        prefix = f"opportunity:{channel}:user:"
        for key, _ in redis_runtime_support.list_json(f"{prefix}*"):
            if not key.startswith(prefix):
                continue
            try:
                result.append(int(key[len(prefix) :]))
            except ValueError:
                continue
        return sorted(set(result))

    def _ticker_key(self, exchange_code: str, market_type: str, symbol: str) -> str:
        return f"market:ticker:{exchange_code}:{market_type}:{symbol}"

    def _funding_key(self, exchange_code: str, symbol: str) -> str:
        return f"market:funding:{exchange_code}:{symbol}"

    def _public_rows_key(self, channel: str) -> str:
        return f"opportunity:{channel}:public"

    def _user_rows_key(self, channel: str, user_id: int) -> str:
        return f"opportunity:{channel}:user:{int(user_id)}"

    def _read_ticker_redis(self, exchange_code: str, market_type: str, symbol: str) -> Optional[TickerCacheItem]:
        payload = redis_runtime_support.get_json(self._ticker_key(exchange_code, market_type, symbol))
        if not isinstance(payload, dict):
            return None
        return self._build_ticker_item(payload, exchange_code=exchange_code, market_type=market_type, symbol=symbol)

    def _read_funding_redis(self, exchange_code: str, symbol: str) -> Optional[FundingRateCacheItem]:
        payload = redis_runtime_support.get_json(self._funding_key(exchange_code, symbol))
        if not isinstance(payload, dict):
            return None
        return self._build_funding_rate_item(payload, exchange_code=exchange_code, symbol=symbol)

    def _read_user_rows_redis(self, channel: str, user_id: int) -> Optional[OpportunityRowsState]:
        return self._read_rows_redis(self._user_rows_key(channel, user_id), channel=channel, user_id=user_id)

    def _read_public_rows_state(self, channel: str) -> Optional[OpportunityRowsState]:
        row_items = self._read_public_row_items(channel)
        if row_items:
            rows = [dict(item.row) for item in row_items]
            meta = row_items[0]
            return OpportunityRowsState(
                channel=channel,
                rows=rows,
                is_ready=bool(meta.is_ready),
                source=str(meta.source or "runtime"),
                generated_at=meta.generated_at,
                updated_at=meta.updated_at,
                message=str(meta.message or ""),
                user_id=None,
            )
        return self._read_rows_redis(self._public_rows_key(channel), channel=channel, user_id=None)

    def _read_rows_redis(self, key: str, *, channel: str, user_id: int | None) -> Optional[OpportunityRowsState]:
        payload = redis_runtime_support.get_json(key)
        if not isinstance(payload, dict):
            return None
        try:
            return OpportunityRowsState(
                channel=str(payload.get("channel") or channel),
                rows=list(payload.get("rows") or []),
                is_ready=bool(payload.get("is_ready")),
                source=str(payload.get("source") or "runtime"),
                generated_at=redis_runtime_support.parse_datetime(payload.get("generated_at")),
                updated_at=redis_runtime_support.parse_datetime(payload.get("updated_at")),
                message=str(payload.get("message") or ""),
                user_id=self._parse_user_id(payload.get("user_id"), fallback=user_id),
            )
        except (TypeError, ValueError):
            return None

    def _sync_public_rows_hash(
        self,
        *,
        channel: str,
        rows: List[dict],
        is_ready: bool,
        source: str,
        generated_at: datetime | None,
        updated_at: datetime | None,
        message: str,
    ) -> None:
        effective_updated_at = updated_at or datetime.now()
        field_payload_map: dict[str, dict] = {}
        for index, row in enumerate(rows, start=1):
            row_key = self._resolve_row_key(channel=channel, row=row, index=index)
            payload = asdict(
                OpportunityRowRuntimeItem(
                    channel=channel,
                    row_key=row_key,
                    row=dict(row),
                    is_ready=is_ready,
                    source=source,
                    generated_at=generated_at,
                    updated_at=effective_updated_at,
                    message=message,
                    user_id=None,
                )
            )
            field_payload_map[row_key] = payload
        redis_runtime_support.sync_hash_json(
            self._public_rows_key(channel),
            field_payload_map,
            ttl_seconds=OPPORTUNITY_ROWS_TTL_SECONDS,
        )

    def _read_public_row_items(self, channel: str) -> List[OpportunityRowRuntimeItem]:
        payload_map = redis_runtime_support.get_hash_json(self._public_rows_key(channel))
        if not payload_map:
            return []
        result: List[OpportunityRowRuntimeItem] = []
        for fallback_index, (field, payload) in enumerate(payload_map.items(), start=1):
            if not isinstance(payload, dict):
                continue
            item = self._build_public_row_item(
                payload,
                channel=channel,
                fallback_row_key=str(field),
                fallback_index=fallback_index,
            )
            if item is not None:
                result.append(item)
        return self._sort_public_row_items(result)

    def _build_public_row_item(
        self,
        payload: dict,
        *,
        channel: str,
        fallback_row_key: str,
        fallback_index: int,
    ) -> Optional[OpportunityRowRuntimeItem]:
        row = payload.get("row")
        if not isinstance(row, dict):
            return None
        row_key = str(payload.get("row_key") or fallback_row_key or self._resolve_row_key(channel=channel, row=row, index=fallback_index)).strip()
        if not row_key:
            row_key = self._resolve_row_key(channel=channel, row=row, index=fallback_index)
        try:
            return OpportunityRowRuntimeItem(
                channel=str(payload.get("channel") or channel),
                row_key=row_key,
                row=dict(row),
                is_ready=bool(payload.get("is_ready")),
                source=str(payload.get("source") or "runtime"),
                generated_at=redis_runtime_support.parse_datetime(payload.get("generated_at")),
                updated_at=redis_runtime_support.parse_datetime(payload.get("updated_at")),
                message=str(payload.get("message") or ""),
                user_id=self._parse_user_id(payload.get("user_id"), fallback=None),
            )
        except (TypeError, ValueError):
            return None

    def _sort_public_row_items(self, items: List[OpportunityRowRuntimeItem]) -> List[OpportunityRowRuntimeItem]:
        return sorted(
            items,
            key=lambda item: (
                self._safe_rank(item.row.get("rank")),
                str(item.row_key),
            ),
        )

    def _safe_rank(self, value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 10**9

    def _resolve_row_key(self, *, channel: str, row: dict, index: int) -> str:
        market_pair_key = str(row.get("market_pair_key") or "").strip()
        if market_pair_key:
            return market_pair_key
        symbol = str(row.get("symbol") or "").strip() or f"row-{index}"
        left_exchange = str(row.get("left_exchange_code") or row.get("buy_exchange") or row.get("long_exchange") or "").strip()
        right_exchange = str(row.get("right_exchange_code") or row.get("sell_exchange") or row.get("short_exchange") or "").strip()
        return ":".join(part for part in (channel, symbol, left_exchange, right_exchange, str(index)) if part)

    def _parse_user_id(self, value: object, *, fallback: int | None) -> int | None:
        if value in (None, ""):
            return fallback
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _build_ticker_item(
        self,
        payload: dict,
        *,
        exchange_code: str = "",
        market_type: str = "",
        symbol: str = "",
    ) -> Optional[TickerCacheItem]:
        try:
            return TickerCacheItem(
                exchange_code=str(payload.get("exchange_code") or exchange_code),
                market_type=str(payload.get("market_type") or market_type),
                symbol=str(payload.get("symbol") or symbol),
                last_price=float(payload.get("last_price") or 0),
                bid_price=float(payload.get("bid_price") or 0),
                ask_price=float(payload.get("ask_price") or 0),
                quote_volume=float(payload.get("quote_volume") or 0),
                synced_at=redis_runtime_support.parse_datetime(payload.get("synced_at")),
            )
        except (TypeError, ValueError):
            return None

    def _build_funding_rate_item(
        self,
        payload: dict,
        *,
        exchange_code: str = "",
        symbol: str = "",
    ) -> Optional[FundingRateCacheItem]:
        try:
            return FundingRateCacheItem(
                exchange_code=str(payload.get("exchange_code") or exchange_code),
                symbol=str(payload.get("symbol") or symbol),
                funding_rate_percent=float(payload.get("funding_rate_percent") or 0),
                next_funding_at=redis_runtime_support.parse_datetime(payload.get("next_funding_at")),
                synced_at=redis_runtime_support.parse_datetime(payload.get("synced_at")),
                settlement_interval_hours=float(payload.get("settlement_interval_hours") or 0) or None,
            )
        except (TypeError, ValueError):
            return None


market_runtime_cache = MarketRuntimeCache()
