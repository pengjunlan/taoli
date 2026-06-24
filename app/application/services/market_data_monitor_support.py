from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from app.application.services.market_data_monitor_models import BackfillTaskSpec, WatchTarget
from app.application.services.swap_market_rules import is_u_margin_linear_swap_market
from app.infrastructure.cache import market_runtime_cache
from app.infrastructure.persistence.market_repository import market_repository


def collect_watch_targets(enabled_exchange_codes: List[str]) -> tuple[List[WatchTarget], set[str]]:
    if not enabled_exchange_codes:
        return [], set()

    watch_targets: Dict[Tuple[str, str, str], WatchTarget] = {}
    market_rows = market_repository.list_active_markets(
        exchange_codes=enabled_exchange_codes,
        market_type="swap",
    )
    synced_exchange_codes: set[str] = set()
    for row in market_rows:
        exchange_code = str(row.get("exchange_code") or "")
        market_type = str(row.get("market_type") or "")
        symbol = str(row.get("symbol") or "")
        if not exchange_code or market_type != "swap" or not symbol:
            continue
        if not is_u_margin_linear_swap_market(row):
            continue
        if not bool(row.get("supports_ws", True)):
            continue
        synced_exchange_codes.add(exchange_code)
        watch_targets[(exchange_code, market_type, symbol)] = WatchTarget(
            exchange_code=exchange_code,
            market_type=market_type,
            symbol=symbol,
        )

    return sorted(
        watch_targets.values(),
        key=lambda item: (item.exchange_code, item.market_type, item.symbol),
    ), synced_exchange_codes


def collect_backfill_targets(enabled_exchange_codes: List[str]) -> List[WatchTarget]:
    if not enabled_exchange_codes:
        return []

    backfill_targets: Dict[Tuple[str, str, str], WatchTarget] = {}
    for row in market_repository.list_active_pairs():
        legs = (
            (
                str(row.get("left_exchange_code") or "").strip(),
                str(row.get("left_market_type") or "").strip(),
                str(row.get("left_symbol") or "").strip(),
            ),
            (
                str(row.get("right_exchange_code") or "").strip(),
                str(row.get("right_market_type") or "").strip(),
                str(row.get("right_symbol") or "").strip(),
            ),
        )
        for exchange_code, market_type, symbol in legs:
            if exchange_code not in enabled_exchange_codes or market_type != "swap" or not symbol:
                continue
            backfill_targets[(exchange_code, market_type, symbol)] = WatchTarget(
                exchange_code=exchange_code,
                market_type=market_type,
                symbol=symbol,
            )

    if not backfill_targets:
        market_rows = market_repository.list_active_markets(
            exchange_codes=enabled_exchange_codes,
            market_type="swap",
        )
        for row in market_rows:
            exchange_code = str(row.get("exchange_code") or "")
            market_type = str(row.get("market_type") or "")
            symbol = str(row.get("symbol") or "")
            if not exchange_code or market_type != "swap" or not symbol:
                continue
            if not is_u_margin_linear_swap_market(row):
                continue
            backfill_targets[(exchange_code, market_type, symbol)] = WatchTarget(
                exchange_code=exchange_code,
                market_type=market_type,
                symbol=symbol,
            )

    return sorted(
        backfill_targets.values(),
        key=lambda item: (item.exchange_code, item.market_type, item.symbol),
    )


def chunk_symbols(symbols: List[str], chunk_size: int) -> List[List[str]]:
    if chunk_size <= 0:
        return [list(symbols)]
    return [symbols[index:index + chunk_size] for index in range(0, len(symbols), chunk_size)]


def build_backfill_task_specs(
    targets: List[WatchTarget],
    *,
    enable_http_ticker_backfill: bool,
    enable_http_funding_backfill: bool,
    ticker_chunk_size_resolver,
    symbol_priority_sorter,
) -> List[BackfillTaskSpec]:
    ticker_groups: Dict[tuple[str, str], List[str]] = {}
    funding_groups: Dict[str, List[str]] = {}

    for item in targets:
        ticker_groups.setdefault((item.exchange_code, item.market_type), []).append(str(item.symbol))
        if item.market_type == "swap":
            funding_groups.setdefault(item.exchange_code, []).append(str(item.symbol))

    specs: List[BackfillTaskSpec] = []
    if enable_http_ticker_backfill:
        for (exchange_code, market_type), symbols in sorted(ticker_groups.items()):
            ordered_symbols = symbol_priority_sorter(
                exchange_code=exchange_code,
                market_type=market_type,
                task_type="ticker",
                symbols=symbols,
            )
            chunk_size = ticker_chunk_size_resolver(
                exchange_code=exchange_code,
                task_type="ticker",
            )
            chunks = chunk_symbols(ordered_symbols, chunk_size)
            for chunk_index, symbol_chunk in enumerate(chunks, start=1):
                specs.append(
                    BackfillTaskSpec(
                        task_key=f"{exchange_code}:{market_type}:ticker:{chunk_index}",
                        exchange_code=exchange_code,
                        market_type=market_type,
                        task_type="ticker",
                        symbols=tuple(symbol_chunk),
                        chunk_index=chunk_index,
                        chunk_total=len(chunks),
                    )
                )
    if enable_http_funding_backfill:
        for exchange_code, symbols in sorted(funding_groups.items()):
            ordered_symbols = symbol_priority_sorter(
                exchange_code=exchange_code,
                market_type="swap",
                task_type="funding",
                symbols=symbols,
            )
            chunk_size = ticker_chunk_size_resolver(
                exchange_code=exchange_code,
                task_type="funding",
            )
            chunks = chunk_symbols(ordered_symbols, chunk_size)
            for chunk_index, symbol_chunk in enumerate(chunks, start=1):
                specs.append(
                    BackfillTaskSpec(
                        task_key=f"{exchange_code}:swap:funding:{chunk_index}",
                        exchange_code=exchange_code,
                        market_type="swap",
                        task_type="funding",
                        symbols=tuple(symbol_chunk),
                        chunk_index=chunk_index,
                        chunk_total=len(chunks),
                    )
                )
    return specs


def sort_symbols_by_backfill_priority(
    *,
    exchange_code: str,
    market_type: str,
    task_type: str,
    symbols: Iterable[str],
) -> List[str]:
    unique_symbols = sorted({str(item).strip() for item in symbols if str(item).strip()})
    if not unique_symbols:
        return []

    def sort_key(symbol: str) -> tuple[int, float, str]:
        if task_type == "ticker":
            item = market_runtime_cache.get_ticker(exchange_code, market_type, symbol)
            if item is None or item.synced_at is None:
                return (0, 0.0, symbol)
            if float(item.last_price or 0) <= 0 or float(item.bid_price or 0) <= 0 or float(item.ask_price or 0) <= 0:
                return (1, item.synced_at.timestamp(), symbol)
            return (2, item.synced_at.timestamp(), symbol)

        item = market_runtime_cache.get_funding_rate(exchange_code, symbol)
        if item is None or item.synced_at is None:
            return (0, 0.0, symbol)
        if float(item.funding_rate_percent or 0) == 0 and item.next_funding_at is None:
            return (1, item.synced_at.timestamp(), symbol)
        return (2, item.synced_at.timestamp(), symbol)

    return sorted(unique_symbols, key=sort_key)


def summarize_watch_targets(watch_targets: List[WatchTarget]) -> tuple[tuple[str, int], ...]:
    summary: Dict[str, int] = defaultdict(int)
    for item in watch_targets:
        summary[item.exchange_code] += 1
    return tuple(sorted(summary.items()))
