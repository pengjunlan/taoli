"""System-level public market data monitor backed by perpetual WebSocket streams."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import threading
import time
from typing import Deque, Dict, Iterable, List, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import aiohttp
from aiohttp.resolver import ThreadedResolver
import ccxt

from app.application.services.market_sync_service import market_sync_service
from app.application.services.monitor_center_service import monitor_center_service
from app.application.services.swap_market_rules import is_u_margin_linear_swap_market
from app.domain.entities.monitor_models import MarketOpportunity, ServiceHeartbeat
from app.infrastructure.cache import FundingRateCacheItem, TickerCacheItem, market_runtime_cache
from app.infrastructure.persistence.market_repository import market_repository


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchTarget:
    exchange_code: str
    market_type: str
    symbol: str


@dataclass(frozen=True)
class ExchangeWsTarget:
    exchange_code: str
    market_type: str
    symbol: str
    ws_symbol: str


@dataclass(frozen=True)
class BackfillTaskSpec:
    task_key: str
    exchange_code: str
    market_type: str
    task_type: str
    symbols: Tuple[str, ...]
    chunk_index: int = 1
    chunk_total: int = 1


@dataclass
class BackfillTaskState:
    task_key: str
    exchange_code: str
    market_type: str
    task_type: str
    symbol_count: int = 0
    is_running: bool = False
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_duration_ms: int = 0
    last_success_count: int = 0
    last_missing_count: int = 0
    last_error_message: str = ""
    last_round_id: int = 0


class MarketDataMonitorService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._funding_thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._interval_seconds = 2
        self._market_sync_interval_seconds = 60 * 60
        self._ticker_refresh_interval_seconds = 15
        self._funding_refresh_interval_seconds = 15
        self._backfill_schedule_interval_seconds = 15
        self._backfill_heartbeat_interval_seconds = 3
        self._backfill_request_timeout_seconds = 8
        self._backfill_ticker_chunk_size = 120
        self._backfill_funding_chunk_size = 80
        self._backfill_bitget_ticker_chunk_size = 40
        self._backfill_bitget_funding_chunk_size = 30
        self._backfill_bitget_retry_attempts = 3
        self._backfill_bitget_retry_delay_seconds = 0.5
        self._ws_cycle_max_seconds = 300
        self._monitor_key = "market_data_monitor"
        self._backfill_monitor_key = "market_data_backfill_monitor"
        self._enable_catalog_sync = False
        self._enable_http_ticker_backfill = True
        self._enable_http_funding_backfill = True
        self._ws_log_flush_interval_seconds = 1.0
        self._ws_log_group_limit = 40
        self._ws_log_queue_limit = 5000
        self._last_market_sync_at: datetime | None = None
        self._last_ticker_refresh_at: datetime | None = None
        self._last_funding_refresh_at: datetime | None = None
        self._last_status = "idle"
        self._last_detail = "waiting for startup"
        self._log_queue: Deque[dict] = deque()
        self._log_queue_lock = threading.Lock()
        self._runtime_mode_notice_emitted = False
        self._last_missing_market_exchange_codes: tuple[str, ...] = ()
        self._last_watch_target_summary_signature: tuple[tuple[str, int], ...] = ()
        self._backfill_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=8,
            thread_name_prefix="market-backfill",
        )
        self._backfill_state_lock = threading.Lock()
        self._backfill_futures: Dict[str, concurrent.futures.Future] = {}
        self._backfill_task_states: Dict[str, BackfillTaskState] = {}
        self._backfill_round_id = 0

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            monitor_center_service.register_worker(
                key=self._monitor_key,
                name="系统公共行情线程",
                category="市场监控",
                thread_name="market-data-monitor",
                interval_seconds=self._interval_seconds,
                status="starting",
                detail="准备同步系统交易所市场目录并切换为永续合约 WebSocket 订阅",
            )
            self._thread = threading.Thread(
                target=self._run_loop,
                name="market-data-monitor",
                daemon=True,
            )
            self._thread.start()
            if self._enable_http_funding_backfill:
                monitor_center_service.register_worker(
                    key=self._backfill_monitor_key,
                    name="行情补位线程",
                    category="市场监控",
                    thread_name="market-funding-monitor",
                    interval_seconds=self._funding_refresh_interval_seconds,
                    status="starting",
                    detail="准备每分钟主动回补 tick 与资金费数据",
                )
                self._funding_thread = threading.Thread(
                    target=self._run_backfill_loop,
                    name="market-funding-monitor",
                    daemon=True,
                )
                self._funding_thread.start()

    def heartbeat(self) -> ServiceHeartbeat:
        return ServiceHeartbeat(
            name="market_data_monitor",
            status=self._last_status,
            detail=self._last_detail,
        )

    def collect_opportunities(self) -> List[MarketOpportunity]:
        return []

    def _run_loop(self) -> None:
        while True:
            try:
                monitor_center_service.heartbeat(
                    self._monitor_key,
                    status="running",
                    detail="线程心跳正常，准备同步市场目录并维持永续行情 WebSocket 连接",
                )
                if self._enable_catalog_sync:
                    self._try_market_catalog_sync()
                targets = self._collect_watch_targets()
                if not targets:
                    message = "当前没有启用的永续合约配对，公共行情线程等待中"
                    self._last_status = "running"
                    self._last_detail = message
                    monitor_center_service.mark_success(self._monitor_key, message)
                    time.sleep(self._interval_seconds)
                    continue

                self._emit_runtime_mode_notice_once(targets)
                self._emit_watch_target_summary(targets)
                self._run_ws_cycle(targets)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Market data monitor failed: %s", exc)
                self._last_status = "error"
                self._last_detail = str(exc)
                monitor_center_service.mark_error(self._monitor_key, f"系统公共行情线程异常: {exc}")
                time.sleep(self._interval_seconds)

    def _run_funding_loop(self) -> None:
        while True:
            try:
                monitor_center_service.heartbeat(
                    self._backfill_monitor_key,
                    status="running",
                    detail="正在执行每分钟 tick / 资金费回补",
                )
                if self._enable_catalog_sync:
                    self._try_market_catalog_sync()
                targets = self._collect_backfill_targets()
                if targets and self._enable_http_ticker_backfill:
                    self._refresh_public_tickers_if_needed(targets)
                if targets and self._enable_http_funding_backfill:
                    self._refresh_public_funding_rates_if_needed(targets)
                monitor_center_service.mark_success(
                    self._backfill_monitor_key,
                    "每分钟 tick / 资金费回补已执行完成",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Funding refresh side loop failed: %s", exc)
                monitor_center_service.add_log(
                    self._monitor_key,
                    "warning",
                    f"资金费后台补位异常: {exc}",
                )
            time.sleep(self._funding_refresh_interval_seconds)

    def _run_backfill_loop(self) -> None:
        while True:
            try:
                monitor_center_service.heartbeat(
                    self._backfill_monitor_key,
                    status="running",
                    detail="正在执行每分钟 tick / 资金费回补",
                )
                if self._enable_catalog_sync:
                    self._try_market_catalog_sync()
                targets = self._collect_backfill_targets()
                if targets and self._enable_http_ticker_backfill:
                    self._refresh_public_tickers_if_needed(targets)
                if targets and self._enable_http_funding_backfill:
                    self._refresh_public_funding_rates_if_needed(targets)
                monitor_center_service.mark_success(
                    self._backfill_monitor_key,
                    "每分钟 tick / 资金费回补已执行完成",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Backfill side loop failed: %s", exc)
                monitor_center_service.mark_error(
                    self._backfill_monitor_key,
                    f"行情回补异常: {exc}",
                )
                monitor_center_service.add_log(
                    self._backfill_monitor_key,
                    "warning",
                    f"行情回补异常: {exc}",
                )
            time.sleep(self._funding_refresh_interval_seconds)

    def _ensure_market_catalog_sync(self) -> None:
        now = datetime.now()
        if (
            self._last_market_sync_at is not None
            and (now - self._last_market_sync_at).total_seconds() < self._market_sync_interval_seconds
        ):
            return

        result = market_sync_service.sync_all_public_markets()
        self._last_market_sync_at = now
        monitor_center_service.add_log(
            self._monitor_key,
            "info",
            (
                f"市场目录已同步：市场 {result['market_count']} 条，"
                f"资金费配对 {result['funding_pair_count']} 条，"
                f"价差配对 {result['spread_pair_count']} 条"
            ),
        )

    def _try_market_catalog_sync(self) -> None:
        try:
            self._ensure_market_catalog_sync()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Market catalog sync skipped this round: %s", exc)
            monitor_center_service.add_log(
                self._monitor_key,
                "warning",
                f"市场目录同步失败，已跳过本轮同步并继续使用现有配对表: {exc}",
            )

    def _collect_watch_targets(self) -> List[WatchTarget]:
        enabled_exchange_codes = sorted(set(market_sync_service.list_supported_exchange_codes()))
        if not enabled_exchange_codes:
            return []

        watch_targets: Dict[Tuple[str, str, str], WatchTarget] = {}
        market_rows = market_repository.list_active_markets(
            exchange_codes=enabled_exchange_codes,
            market_type="swap",
        )
        synced_exchange_codes = set()
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

        self._emit_missing_market_notice(
            enabled_exchange_codes=enabled_exchange_codes,
            synced_exchange_codes=synced_exchange_codes,
        )

        return sorted(
            watch_targets.values(),
            key=lambda item: (item.exchange_code, item.market_type, item.symbol),
        )

    def _collect_backfill_targets(self) -> List[WatchTarget]:
        enabled_exchange_codes = sorted(set(market_sync_service.list_supported_exchange_codes()))
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

    def _emit_runtime_mode_notice_once(self, watch_targets: List[WatchTarget]) -> None:
        if self._runtime_mode_notice_emitted:
            return
        exchange_codes = sorted({item.exchange_code for item in watch_targets})
        if not exchange_codes:
            return
        monitor_center_service.add_log(
            self._monitor_key,
            "info",
            f"系统公共行情线程将按系统交易所启用配置订阅永续实时行情: {','.join(exchange_codes)}",
        )
        self._runtime_mode_notice_emitted = True

    def _emit_missing_market_notice(
        self,
        *,
        enabled_exchange_codes: List[str],
        synced_exchange_codes: set[str],
    ) -> None:
        missing_exchange_codes = tuple(
            sorted(code for code in enabled_exchange_codes if code not in synced_exchange_codes)
        )
        if missing_exchange_codes == self._last_missing_market_exchange_codes:
            return
        self._last_missing_market_exchange_codes = missing_exchange_codes
        if not missing_exchange_codes:
            return
        monitor_center_service.add_log(
            self._monitor_key,
            "warning",
            "以下已启用交易所当前没有可用的永续市场缓存，暂时无法接入实时推送: "
            + ",".join(missing_exchange_codes),
        )

    def _emit_watch_target_summary(self, watch_targets: List[WatchTarget]) -> None:
        summary: Dict[str, int] = defaultdict(int)
        for item in watch_targets:
            summary[item.exchange_code] += 1
        signature = tuple(sorted(summary.items()))
        if signature == self._last_watch_target_summary_signature:
            return
        self._last_watch_target_summary_signature = signature
        if not signature:
            return
        monitor_center_service.add_log(
            self._monitor_key,
            "info",
            "当前永续行情订阅目标: "
            + ", ".join(f"{exchange_code}={count}" for exchange_code, count in signature),
        )

    def _refresh_public_funding_rates_if_needed(self, watch_targets: List[WatchTarget]) -> None:
        now = datetime.now()
        if (
            self._last_funding_refresh_at is not None
            and (now - self._last_funding_refresh_at).total_seconds() < self._funding_refresh_interval_seconds
        ):
            return

        refreshed_count = self._refresh_public_funding_rates_in_batch(watch_targets)
        self._last_funding_refresh_at = now
        monitor_center_service.add_log(
            self._backfill_monitor_key,
            "info",
            f"资金费率已补位刷新：{refreshed_count} 条",
        )

    def _refresh_public_tickers_if_needed(self, watch_targets: List[WatchTarget]) -> None:
        now = datetime.now()
        if (
            self._last_ticker_refresh_at is not None
            and (now - self._last_ticker_refresh_at).total_seconds() < self._ticker_refresh_interval_seconds
        ):
            return

        refreshed_count = self._refresh_public_tickers_in_batch(watch_targets)
        self._last_ticker_refresh_at = now
        monitor_center_service.add_log(
            self._backfill_monitor_key,
            "info",
            f"Ticker 宸茶ˉ浣嶅埛鏂帮細{refreshed_count} 鏉?",
        )

    def _run_ws_cycle(self, watch_targets: List[WatchTarget]) -> None:
        watch_count = len(watch_targets)
        monitor_center_service.add_log(
            self._monitor_key,
            "info",
            f"开始建立永续 WebSocket 行情订阅，监控目标 {watch_count} 个",
        )
        try:
            if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
                try:
                    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                except Exception:
                    pass
            summary = asyncio.run(self._run_ws_cycle_async(watch_targets))
            message = (
                f"永续 WebSocket 行情运行完成："
                f"ticker {summary['ticker_updates']} 条，"
                f"交易所 {summary['exchange_count']} 个，"
                f"目标市场 {watch_count} 个"
            )
            self._last_status = "running"
            self._last_detail = message
            monitor_center_service.mark_success(self._monitor_key, message)
        finally:
            self._flush_log_queue(force=True)

    async def _run_ws_cycle_async(self, watch_targets: List[WatchTarget]) -> Dict[str, int]:
        cycle_deadline_monotonic = time.monotonic() + self._ws_cycle_max_seconds
        grouped: Dict[str, List[ExchangeWsTarget]] = defaultdict(list)
        for target in watch_targets:
            ws_symbol = self._to_ws_symbol(target.exchange_code, target.symbol)
            if not ws_symbol:
                continue
            grouped[target.exchange_code].append(
                ExchangeWsTarget(
                    exchange_code=target.exchange_code,
                    market_type=target.market_type,
                    symbol=target.symbol,
                    ws_symbol=ws_symbol,
                )
            )

        ticker_counter = {"count": 0}
        connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
        async with aiohttp.ClientSession(trust_env=False, connector=connector) as session:
            tasks = [
                asyncio.create_task(
                    self._run_exchange_ws(
                        session,
                        exchange_code,
                        exchange_targets,
                        ticker_counter,
                        cycle_deadline_monotonic,
                    )
                )
                for exchange_code, exchange_targets in grouped.items()
            ]
            if not tasks:
                return {"ticker_updates": 0, "exchange_count": 0}
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for index, result in enumerate(results):
                if isinstance(result, Exception):
                    exchange_code = list(grouped.keys())[index]
                    monitor_center_service.add_log(
                        self._monitor_key,
                        "warning",
                        f"{exchange_code} 永续 WebSocket 连接失败: {result}",
                    )
        return {"ticker_updates": ticker_counter["count"], "exchange_count": len(grouped)}

    async def _run_exchange_ws(
        self,
        session: aiohttp.ClientSession,
        exchange_code: str,
        targets: List[ExchangeWsTarget],
        ticker_counter: Dict[str, int],
        cycle_deadline_monotonic: float,
    ) -> None:
        try:
            if exchange_code == "bitget":
                await self._run_bitget_ws(session, targets, ticker_counter, cycle_deadline_monotonic)
                return
            if exchange_code == "gate":
                await self._run_gate_ws(session, targets, ticker_counter, cycle_deadline_monotonic)
                return
            if exchange_code == "okx":
                await self._run_okx_ws(session, targets, ticker_counter, cycle_deadline_monotonic)
                return
            if exchange_code == "binance":
                await self._run_binance_ws(session, targets, ticker_counter, cycle_deadline_monotonic)
                return

            monitor_center_service.add_log(
                self._monitor_key,
                "warning",
                f"{exchange_code} 暂未接入 WebSocket 行情适配器",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s websocket runner failed: %s", exchange_code, exc)
            raise

    async def _run_bitget_ws(
        self,
        session: aiohttp.ClientSession,
        targets: List[ExchangeWsTarget],
        ticker_counter: Dict[str, int],
        cycle_deadline_monotonic: float,
    ) -> None:
        url = "wss://ws.bitget.com/v2/ws/public"
        chunk_size = 40
        symbol_map = {item.ws_symbol: item for item in targets}
        chunks = self._chunk_targets(targets, chunk_size)
        tasks = [
            asyncio.create_task(
                self._run_bitget_ws_chunk(
                    session,
                    url,
                    symbol_map,
                    chunk,
                    ticker_counter,
                    cycle_deadline_monotonic,
                )
            )
            for chunk in chunks
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_bitget_ws_chunk(
        self,
        session: aiohttp.ClientSession,
        url: str,
        symbol_map: Dict[str, ExchangeWsTarget],
        chunk: List[ExchangeWsTarget],
        ticker_counter: Dict[str, int],
        cycle_deadline_monotonic: float,
    ) -> None:
        subscribe_payload = {
            "op": "subscribe",
            "args": [
                {
                    "instType": "USDT-FUTURES",
                    "channel": "ticker",
                    "instId": item.ws_symbol,
                }
                for item in chunk
            ],
        }
        async with session.ws_connect(url, heartbeat=20, autoping=True, ssl=True) as ws:
            await ws.send_json(subscribe_payload)
            self._queue_log(
                "info",
                f"Bitget 永续 WebSocket 已订阅 {len(chunk)} 个合约",
            )
            await self._consume_ws_messages(
                ws,
                cycle_deadline_monotonic=cycle_deadline_monotonic,
                on_text=lambda text: self._handle_bitget_message(text, symbol_map, ticker_counter),
            )

    def _handle_bitget_message(
        self,
        text: str,
        symbol_map: Dict[str, ExchangeWsTarget],
        ticker_counter: Dict[str, int],
    ) -> None:
        payload = self._parse_json(text)
        if not isinstance(payload, dict):
            return
        data_rows = payload.get("data") or []
        if not isinstance(data_rows, list):
            return
        for row in data_rows:
            if not isinstance(row, dict):
                continue
            ws_symbol = str(row.get("instId") or row.get("symbol") or "")
            target = symbol_map.get(ws_symbol)
            if target is None:
                continue
            ticker = TickerCacheItem(
                exchange_code=target.exchange_code,
                market_type=target.market_type,
                symbol=target.symbol,
                last_price=self._safe_float(row.get("lastPr")),
                bid_price=self._safe_float(row.get("bidPr"), row.get("lastPr")),
                ask_price=self._safe_float(row.get("askPr"), row.get("lastPr")),
                quote_volume=self._safe_float(row.get("quoteVolume")),
                synced_at=self._parse_ws_datetime(row.get("ts")),
            )
            self._store_ticker_and_log(ticker, ticker_counter)
            funding_rate = self._safe_float(row.get("fundingRate")) * 100
            next_funding_at = self._parse_ws_datetime(row.get("nextFundingTime")) if row.get("nextFundingTime") else None
            if funding_rate != 0 or next_funding_at is not None:
                market_runtime_cache.set_funding_rate(
                    FundingRateCacheItem(
                        exchange_code=target.exchange_code,
                        symbol=target.symbol,
                        funding_rate_percent=funding_rate,
                        next_funding_at=next_funding_at,
                        synced_at=self._parse_ws_datetime(row.get("ts")),
                        settlement_interval_hours=self._resolve_funding_interval_hours(
                            exchange_code=target.exchange_code,
                            payload=row,
                            next_funding_at=next_funding_at,
                        ),
                    )
                )

    async def _run_gate_ws(
        self,
        session: aiohttp.ClientSession,
        targets: List[ExchangeWsTarget],
        ticker_counter: Dict[str, int],
        cycle_deadline_monotonic: float,
    ) -> None:
        url = "wss://fx-ws.gateio.ws/v4/ws/usdt"
        chunk_size = 80
        symbol_map = {item.ws_symbol: item for item in targets}
        chunks = self._chunk_targets(targets, chunk_size)
        tasks = [
            asyncio.create_task(
                self._run_gate_ws_chunk(
                    session,
                    url,
                    symbol_map,
                    chunk,
                    ticker_counter,
                    cycle_deadline_monotonic,
                )
            )
            for chunk in chunks
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_gate_ws_chunk(
        self,
        session: aiohttp.ClientSession,
        url: str,
        symbol_map: Dict[str, ExchangeWsTarget],
        chunk: List[ExchangeWsTarget],
        ticker_counter: Dict[str, int],
        cycle_deadline_monotonic: float,
    ) -> None:
        async with session.ws_connect(url, heartbeat=20, autoping=True, ssl=True) as ws:
            now_ts = int(time.time())
            await ws.send_json(
                {
                    "time": now_ts,
                    "channel": "futures.tickers",
                    "event": "subscribe",
                    "payload": [item.ws_symbol for item in chunk],
                }
            )
            await ws.send_json(
                {
                    "time": now_ts,
                    "channel": "futures.book_ticker",
                    "event": "subscribe",
                    "payload": [item.ws_symbol for item in chunk],
                }
            )
            self._queue_log(
                "info",
                f"Gate 永续 WebSocket 已订阅 {len(chunk)} 个合约（ticker + book_ticker）",
            )
            price_state: Dict[str, Dict[str, float]] = {}
            await self._consume_ws_messages(
                ws,
                cycle_deadline_monotonic=cycle_deadline_monotonic,
                on_text=lambda text: self._handle_gate_message(text, symbol_map, price_state, ticker_counter),
            )

    def _handle_gate_message(
        self,
        text: str,
        symbol_map: Dict[str, ExchangeWsTarget],
        price_state: Dict[str, Dict[str, float]],
        ticker_counter: Dict[str, int],
    ) -> None:
        payload = self._parse_json(text)
        if not isinstance(payload, dict):
            return

        channel = str(payload.get("channel") or "")
        event = str(payload.get("event") or "")
        if event != "update":
            return

        if channel == "futures.tickers":
            rows = payload.get("result") or []
            if not isinstance(rows, list):
                return
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ws_symbol = str(row.get("contract") or "")
                target = symbol_map.get(ws_symbol)
                if target is None:
                    continue
                state = price_state.setdefault(ws_symbol, {})
                state["last_price"] = self._safe_float(row.get("last"))
                state["quote_volume"] = self._safe_float(row.get("volume_24h_quote"), row.get("volume_24h_settle"), row.get("volume_24h"))
                state["synced_at_ms"] = self._safe_float(row.get("t"))
                funding_rate = self._safe_float(row.get("funding_rate")) * 100
                if funding_rate != 0:
                    existing = market_runtime_cache.get_funding_rate(target.exchange_code, target.symbol)
                    market_runtime_cache.set_funding_rate(
                        FundingRateCacheItem(
                            exchange_code=target.exchange_code,
                            symbol=target.symbol,
                            funding_rate_percent=funding_rate,
                            next_funding_at=existing.next_funding_at if existing is not None else None,
                            synced_at=self._parse_ws_datetime(row.get("t")),
                            settlement_interval_hours=(
                                existing.settlement_interval_hours
                                if existing is not None
                                else self._resolve_funding_interval_hours(
                                    exchange_code=target.exchange_code,
                                    payload=row,
                                    next_funding_at=None,
                                )
                            ),
                        )
                    )
                self._maybe_emit_gate_ticker(target, state, ticker_counter)
            return

        if channel == "futures.book_ticker":
            row = payload.get("result") or {}
            if not isinstance(row, dict):
                return
            ws_symbol = str(row.get("s") or "")
            target = symbol_map.get(ws_symbol)
            if target is None:
                return
            state = price_state.setdefault(ws_symbol, {})
            state["bid_price"] = self._safe_float(row.get("b"))
            state["ask_price"] = self._safe_float(row.get("a"))
            state["synced_at_ms"] = self._safe_float(row.get("t"))
            self._maybe_emit_gate_ticker(target, state, ticker_counter)

    def _maybe_emit_gate_ticker(
        self,
        target: ExchangeWsTarget,
        state: Dict[str, float],
        ticker_counter: Dict[str, int],
    ) -> None:
        last_price = float(state.get("last_price") or 0)
        bid_price = float(state.get("bid_price") or 0)
        ask_price = float(state.get("ask_price") or 0)
        if last_price <= 0 or bid_price <= 0 or ask_price <= 0:
            return
        ticker = TickerCacheItem(
            exchange_code=target.exchange_code,
            market_type=target.market_type,
            symbol=target.symbol,
            last_price=last_price,
            bid_price=bid_price,
            ask_price=ask_price,
            quote_volume=float(state.get("quote_volume") or 0),
            synced_at=self._parse_ws_datetime(state.get("synced_at_ms")),
        )
        self._store_ticker_and_log(ticker, ticker_counter)

    async def _run_okx_ws(
        self,
        session: aiohttp.ClientSession,
        targets: List[ExchangeWsTarget],
        ticker_counter: Dict[str, int],
        cycle_deadline_monotonic: float,
    ) -> None:
        url = "wss://ws.okx.com:8443/ws/v5/public"
        chunk_size = 50
        symbol_map = {item.ws_symbol: item for item in targets}
        chunks = self._chunk_targets(targets, chunk_size)
        tasks = [
            asyncio.create_task(
                self._run_okx_ws_chunk(
                    session,
                    url,
                    symbol_map,
                    chunk,
                    ticker_counter,
                    cycle_deadline_monotonic,
                )
            )
            for chunk in chunks
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_okx_ws_chunk(
        self,
        session: aiohttp.ClientSession,
        url: str,
        symbol_map: Dict[str, ExchangeWsTarget],
        chunk: List[ExchangeWsTarget],
        ticker_counter: Dict[str, int],
        cycle_deadline_monotonic: float,
    ) -> None:
        subscribe_payload = {
            "op": "subscribe",
            "args": [
                {
                    "channel": "tickers",
                    "instId": item.ws_symbol,
                }
                for item in chunk
            ],
        }
        async with session.ws_connect(url, heartbeat=20, autoping=True, ssl=True) as ws:
            await ws.send_json(subscribe_payload)
            self._queue_log(
                "info",
                f"OKX 永续 WebSocket 已订阅 {len(chunk)} 个合约",
            )
            await self._consume_ws_messages(
                ws,
                cycle_deadline_monotonic=cycle_deadline_monotonic,
                on_text=lambda text: self._handle_okx_message(text, symbol_map, ticker_counter),
            )

    def _handle_okx_message(
        self,
        text: str,
        symbol_map: Dict[str, ExchangeWsTarget],
        ticker_counter: Dict[str, int],
    ) -> None:
        payload = self._parse_json(text)
        if not isinstance(payload, dict):
            return
        data_rows = payload.get("data") or []
        if not isinstance(data_rows, list):
            return
        for row in data_rows:
            if not isinstance(row, dict):
                continue
            ws_symbol = str(row.get("instId") or "")
            target = symbol_map.get(ws_symbol)
            if target is None:
                continue
            ticker = TickerCacheItem(
                exchange_code=target.exchange_code,
                market_type=target.market_type,
                symbol=target.symbol,
                last_price=self._safe_float(row.get("last")),
                bid_price=self._safe_float(row.get("bidPx"), row.get("last")),
                ask_price=self._safe_float(row.get("askPx"), row.get("last")),
                quote_volume=self._safe_float(row.get("volCcy24h"), row.get("vol24h")),
                synced_at=self._parse_ws_datetime(row.get("ts")),
            )
            self._store_ticker_and_log(ticker, ticker_counter)

    async def _run_binance_ws(
        self,
        session: aiohttp.ClientSession,
        targets: List[ExchangeWsTarget],
        ticker_counter: Dict[str, int],
        cycle_deadline_monotonic: float,
    ) -> None:
        base_url = "wss://fstream.binance.com/ws"
        chunk_size = 80
        symbol_map = {item.ws_symbol: item for item in targets}
        chunks = self._chunk_targets(targets, chunk_size)
        tasks = [
            asyncio.create_task(
                self._run_binance_ws_chunk(
                    session,
                    base_url,
                    symbol_map,
                    chunk,
                    ticker_counter,
                    cycle_deadline_monotonic,
                )
            )
            for chunk in chunks
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_binance_ws_chunk(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        symbol_map: Dict[str, ExchangeWsTarget],
        chunk: List[ExchangeWsTarget],
        ticker_counter: Dict[str, int],
        cycle_deadline_monotonic: float,
    ) -> None:
        streams = [f"{item.ws_symbol.lower()}@bookTicker" for item in chunk]
        url = f"{base_url}/stream?streams={'/'.join(streams)}"
        async with session.ws_connect(url, heartbeat=20, autoping=True, ssl=True) as ws:
            self._queue_log(
                "info",
                f"Binance 永续 WebSocket 已订阅 {len(chunk)} 个合约",
            )
            await self._consume_ws_messages(
                ws,
                cycle_deadline_monotonic=cycle_deadline_monotonic,
                on_text=lambda text: self._handle_binance_message(text, symbol_map, ticker_counter),
            )

    def _handle_binance_message(
        self,
        text: str,
        symbol_map: Dict[str, ExchangeWsTarget],
        ticker_counter: Dict[str, int],
    ) -> None:
        payload = self._parse_json(text)
        if not isinstance(payload, dict):
            return
        row = payload.get("data") or payload
        if not isinstance(row, dict):
            return
        ws_symbol = str(row.get("s") or "")
        target = symbol_map.get(ws_symbol)
        if target is None:
            return
        bid_price = self._safe_float(row.get("b"))
        ask_price = self._safe_float(row.get("a"))
        last_price = bid_price if bid_price > 0 else ask_price
        ticker = TickerCacheItem(
            exchange_code=target.exchange_code,
            market_type=target.market_type,
            symbol=target.symbol,
            last_price=last_price,
            bid_price=bid_price if bid_price > 0 else last_price,
            ask_price=ask_price if ask_price > 0 else last_price,
            quote_volume=0.0,
            synced_at=self._parse_ws_datetime(row.get("E") or row.get("T")),
        )
        self._store_ticker_and_log(ticker, ticker_counter)

    async def _consume_ws_messages(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        *,
        cycle_deadline_monotonic: float,
        on_text,
    ) -> None:
        last_log_flush_monotonic = time.monotonic()
        while True:
            if time.monotonic() >= cycle_deadline_monotonic:
                break
            try:
                message = await ws.receive(timeout=30)
            except asyncio.TimeoutError:
                self._flush_log_queue(force=False)
                monitor_center_service.heartbeat(
                    self._monitor_key,
                    status="running",
                    detail="永续 WebSocket 连接保持中，等待新的市场推送",
                )
                continue
            if message.type == aiohttp.WSMsgType.TEXT:
                on_text(str(message.data))
            elif message.type == aiohttp.WSMsgType.BINARY:
                try:
                    on_text(message.data.decode("utf-8", errors="ignore"))
                except Exception:
                    pass
            elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR}:
                break

            now_monotonic = time.monotonic()
            if now_monotonic - last_log_flush_monotonic >= self._ws_log_flush_interval_seconds:
                self._flush_log_queue(force=False)
                monitor_center_service.heartbeat(
                    self._monitor_key,
                    status="running",
                    detail="永续 WebSocket 连接正常，正在接收并写入 Redis",
                )
                last_log_flush_monotonic = now_monotonic

    def _store_ticker_and_log(self, ticker: TickerCacheItem, ticker_counter: Dict[str, int]) -> None:
        if ticker.last_price <= 0:
            return
        market_runtime_cache.set_ticker(ticker)
        ticker_counter["count"] += 1
        self._queue_log(
            "info",
            (
                f"{ticker.exchange_code} {ticker.symbol} 推送: "
                f"last={ticker.last_price:.8f} "
                f"bid={ticker.bid_price:.8f} "
                f"ask={ticker.ask_price:.8f}"
            ),
        )

    def _queue_log(self, level: str, message: str) -> None:
        with self._log_queue_lock:
            while len(self._log_queue) >= self._ws_log_queue_limit:
                self._log_queue.popleft()
            self._log_queue.append(
                {
                    "time": datetime.now().isoformat(sep=" ", timespec="seconds"),
                    "level": level.upper(),
                    "message": message,
                }
            )

    def _flush_log_queue(self, *, force: bool) -> None:
        with self._log_queue_lock:
            if not self._log_queue:
                return
            if not force and len(self._log_queue) < self._ws_log_group_limit:
                return
            entries = list(self._log_queue)
            self._log_queue.clear()
        monitor_center_service.add_logs(self._monitor_key, entries)

    def _chunk_targets(self, targets: List[ExchangeWsTarget], chunk_size: int) -> List[List[ExchangeWsTarget]]:
        if chunk_size <= 0:
            return [list(targets)]
        return [targets[index:index + chunk_size] for index in range(0, len(targets), chunk_size)]

    def _refresh_public_tickers_in_batch(self, watch_targets: List[WatchTarget]) -> int:
        grouped: Dict[tuple[str, str], List[str]] = {}
        for item in watch_targets:
            grouped.setdefault((item.exchange_code, item.market_type), []).append(str(item.symbol))

        refreshed_count = 0
        for (exchange_code, market_type), symbols in grouped.items():
            unique_symbols = sorted(set(symbols))
            batch: Dict[str, TickerCacheItem] = {}
            error_messages: List[str] = []
            for symbol_chunk in self._chunk_symbols(unique_symbols, self._ticker_batch_size):
                try:
                    batch.update(
                        self._fetch_public_tickers(
                            exchange_code=exchange_code,
                            market_type=market_type,
                            symbols=symbol_chunk,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    error_messages.append(str(exc))

            for symbol in unique_symbols:
                ticker_data = batch.get(symbol)
                if ticker_data is None:
                    continue
                market_runtime_cache.set_ticker(ticker_data)
                refreshed_count += 1

            success_count = len(batch)
            monitor_center_service.add_log(
                self._backfill_monitor_key,
                "info",
                (
                    f"{exchange_code} Ticker 回补 {success_count}/{len(unique_symbols)} 条"
                    + self._format_ticker_samples(batch)
                ),
            )

            missing_count = len(unique_symbols) - len(batch)
            if missing_count > 0:
                monitor_center_service.add_log(
                    self._backfill_monitor_key,
                    "warning",
                    f"{exchange_code} Ticker 批量返回缺失 {missing_count} 条",
                )
            if error_messages:
                monitor_center_service.add_log(
                    self._backfill_monitor_key,
                    "warning",
                    f"{exchange_code} Ticker 本轮批量补位异常 {len(error_messages)} 次: {' | '.join(error_messages[:3])}",
                )
        return refreshed_count

    def _refresh_public_funding_rates_in_batch(self, watch_targets: List[WatchTarget]) -> int:
        grouped: Dict[str, List[str]] = {}
        for item in watch_targets:
            if item.market_type != "swap":
                continue
            grouped.setdefault(item.exchange_code, []).append(str(item.symbol))

        refreshed_count = 0
        for exchange_code, symbols in grouped.items():
            unique_symbols = sorted(set(symbols))
            batch: Dict[str, FundingRateCacheItem] = {}
            error_messages: List[str] = []
            for symbol_chunk in self._chunk_symbols(unique_symbols, self._funding_batch_size):
                try:
                    batch.update(
                        self._fetch_public_funding_rates(
                            exchange_code=exchange_code,
                            symbols=symbol_chunk,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    error_messages.append(str(exc))

            for symbol in unique_symbols:
                funding_data = batch.get(symbol)
                if funding_data is None:
                    continue
                market_runtime_cache.set_funding_rate(funding_data)
                refreshed_count += 1

            success_count = len(batch)
            monitor_center_service.add_log(
                self._backfill_monitor_key,
                "info",
                (
                    f"{exchange_code} 资金费回补 {success_count}/{len(unique_symbols)} 条"
                    + self._format_funding_samples(batch)
                ),
            )
            missing_count = len(unique_symbols) - len(batch)
            if missing_count > 0:
                monitor_center_service.add_log(
                    self._backfill_monitor_key,
                    "warning",
                    f"{exchange_code} 资金费批量返回缺失 {missing_count} 条，已跳过逐条兜底以避免阻塞价格流",
                )
            if error_messages:
                monitor_center_service.add_log(
                    self._backfill_monitor_key,
                    "warning",
                    f"{exchange_code} 资金费本轮批量补位异常 {len(error_messages)} 次: {' | '.join(error_messages[:3])}",
                )
        return refreshed_count

    def _chunk_symbols(self, symbols: List[str], chunk_size: int) -> List[List[str]]:
        if chunk_size <= 0:
            return [list(symbols)]
        return [symbols[index:index + chunk_size] for index in range(0, len(symbols), chunk_size)]

    def _fetch_public_tickers(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbols: List[str],
    ) -> Dict[str, TickerCacheItem]:
        if exchange_code == "bitget":
            return self._fetch_bitget_swap_tickers(symbols)
        if exchange_code == "gate":
            return self._fetch_gate_swap_tickers(symbols)
        if exchange_code == "okx":
            return self._fetch_okx_swap_tickers(symbols)
        if exchange_code == "binance":
            return self._fetch_binance_swap_tickers(symbols)

        exchange = self._build_public_exchange(exchange_code=exchange_code, market_type=market_type)
        try:
            if exchange.has.get("fetchTickers"):
                payload = exchange.fetch_tickers(symbols)
            elif exchange.has.get("fetchTicker"):
                payload = {symbol: exchange.fetch_ticker(symbol) for symbol in symbols}
            else:
                return {}

            result: Dict[str, TickerCacheItem] = {}
            for symbol, item in payload.items():
                row = item or {}
                normalized_symbol = str(row.get("symbol") or symbol or "")
                if not normalized_symbol:
                    continue
                last_price = self._safe_float(row.get("last"), row.get("close"), row.get("bid"), row.get("ask"))
                bid_price = self._safe_float(row.get("bid"), row.get("last"), row.get("close"))
                ask_price = self._safe_float(row.get("ask"), row.get("last"), row.get("close"))
                if last_price <= 0 and bid_price <= 0 and ask_price <= 0:
                    continue
                fallback_last_price = max(last_price, bid_price, ask_price)
                result[normalized_symbol] = TickerCacheItem(
                    exchange_code=exchange_code,
                    market_type=market_type,
                    symbol=normalized_symbol,
                    last_price=fallback_last_price,
                    bid_price=bid_price if bid_price > 0 else fallback_last_price,
                    ask_price=ask_price if ask_price > 0 else fallback_last_price,
                    quote_volume=self._safe_float(row.get("quoteVolume"), row.get("baseVolume")),
                    synced_at=self._parse_backfill_datetime(row.get("timestamp") or row.get("datetime")),
                )
            return result
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def _fetch_bitget_swap_tickers(self, symbols: List[str]) -> Dict[str, TickerCacheItem]:
        if not symbols:
            return {}
        last_error: Exception | None = None
        for attempt in range(1, self._backfill_bitget_retry_attempts + 1):
            try:
                payload = self._http_get_json(
                    "https://api.bitget.com/api/v2/mix/market/tickers",
                    params={"productType": "USDT-FUTURES"},
                )
                rows = payload.get("data") if isinstance(payload, dict) else []
                if not isinstance(rows, list):
                    return {}
                target_symbols = set(symbols)
                result: Dict[str, TickerCacheItem] = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    symbol = self._normalize_rest_symbol("bitget", str(row.get("symbol") or row.get("instId") or ""))
                    if not symbol or symbol not in target_symbols:
                        continue
                    ticker = self._build_ticker_from_values(
                        exchange_code="bitget",
                        market_type="swap",
                        symbol=symbol,
                        last_price=self._safe_float(row.get("lastPr")),
                        bid_price=self._safe_float(row.get("bidPr"), row.get("lastPr")),
                        ask_price=self._safe_float(row.get("askPr"), row.get("lastPr")),
                        quote_volume=self._safe_float(row.get("quoteVolume"), row.get("usdtVolume")),
                        synced_at=self._parse_backfill_datetime(row.get("ts")),
                    )
                    if ticker is not None:
                        result[symbol] = ticker
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self._backfill_bitget_retry_attempts:
                    break
                time.sleep(self._backfill_bitget_retry_delay_seconds)
        if last_error is not None:
            raise last_error
        return {}

    def _fetch_gate_swap_tickers(self, symbols: List[str]) -> Dict[str, TickerCacheItem]:
        if not symbols:
            return {}
        payload = self._http_get_json(
            "https://api.gateio.ws/api/v4/futures/usdt/tickers",
        )
        rows = payload if isinstance(payload, list) else []
        target_symbols = set(symbols)
        result: Dict[str, TickerCacheItem] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = self._normalize_rest_symbol("gate", str(row.get("contract") or ""))
            if not symbol or symbol not in target_symbols:
                continue
            ticker = self._build_ticker_from_values(
                exchange_code="gate",
                market_type="swap",
                symbol=symbol,
                last_price=self._safe_float(row.get("last")),
                bid_price=self._safe_float(row.get("highest_bid"), row.get("bid_1"), row.get("last")),
                ask_price=self._safe_float(row.get("lowest_ask"), row.get("ask_1"), row.get("last")),
                quote_volume=self._safe_float(row.get("volume_24h_quote"), row.get("volume_24h_settle"), row.get("volume_24h")),
                synced_at=datetime.now(),
            )
            if ticker is not None:
                result[symbol] = ticker
        return result

    def _fetch_okx_swap_tickers(self, symbols: List[str]) -> Dict[str, TickerCacheItem]:
        if not symbols:
            return {}
        payload = self._http_get_json(
            "https://www.okx.com/api/v5/market/tickers",
            params={"instType": "SWAP"},
        )
        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return {}
        target_symbols = set(symbols)
        result: Dict[str, TickerCacheItem] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = self._normalize_rest_symbol("okx", str(row.get("instId") or ""))
            if not symbol or symbol not in target_symbols:
                continue
            ticker = self._build_ticker_from_values(
                exchange_code="okx",
                market_type="swap",
                symbol=symbol,
                last_price=self._safe_float(row.get("last")),
                bid_price=self._safe_float(row.get("bidPx"), row.get("last")),
                ask_price=self._safe_float(row.get("askPx"), row.get("last")),
                quote_volume=self._safe_float(row.get("volCcy24h"), row.get("vol24h")),
                synced_at=self._parse_backfill_datetime(row.get("ts")),
            )
            if ticker is not None:
                result[symbol] = ticker
        return result

    def _fetch_binance_swap_tickers(self, symbols: List[str]) -> Dict[str, TickerCacheItem]:
        if not symbols:
            return {}
        payload = self._http_get_json(
            "https://fapi.binance.com/fapi/v1/ticker/bookTicker",
        )
        rows = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
        target_symbols = set(symbols)
        result: Dict[str, TickerCacheItem] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = self._normalize_rest_symbol("binance", str(row.get("symbol") or ""))
            if not symbol or symbol not in target_symbols:
                continue
            bid_price = self._safe_float(row.get("bidPrice"))
            ask_price = self._safe_float(row.get("askPrice"))
            last_price = bid_price if bid_price > 0 else ask_price
            ticker = self._build_ticker_from_values(
                exchange_code="binance",
                market_type="swap",
                symbol=symbol,
                last_price=last_price,
                bid_price=bid_price if bid_price > 0 else last_price,
                ask_price=ask_price if ask_price > 0 else last_price,
                quote_volume=0.0,
                synced_at=self._parse_backfill_datetime(row.get("time")),
            )
            if ticker is not None:
                result[symbol] = ticker
        return result

    def _fetch_public_tickers_via_exchange_instance(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbols: List[str],
    ) -> Dict[str, TickerCacheItem]:
        exchange = self._build_public_exchange(exchange_code=exchange_code, market_type=market_type)
        try:
            if exchange.has.get("fetchTickers"):
                payload = exchange.fetch_tickers(symbols)
            elif exchange.has.get("fetchTicker"):
                payload = {symbol: exchange.fetch_ticker(symbol) for symbol in symbols}
            else:
                return {}

            result: Dict[str, TickerCacheItem] = {}
            for symbol, item in payload.items():
                row = item or {}
                normalized_symbol = str(row.get("symbol") or symbol or "")
                if not normalized_symbol:
                    continue
                last_price = self._safe_float(row.get("last"), row.get("close"), row.get("bid"), row.get("ask"))
                bid_price = self._safe_float(row.get("bid"), row.get("last"), row.get("close"))
                ask_price = self._safe_float(row.get("ask"), row.get("last"), row.get("close"))
                if last_price <= 0 and bid_price <= 0 and ask_price <= 0:
                    continue
                fallback_last_price = max(last_price, bid_price, ask_price)
                result[normalized_symbol] = TickerCacheItem(
                    exchange_code=exchange_code,
                    market_type=market_type,
                    symbol=normalized_symbol,
                    last_price=fallback_last_price,
                    bid_price=bid_price if bid_price > 0 else fallback_last_price,
                    ask_price=ask_price if ask_price > 0 else fallback_last_price,
                    quote_volume=self._safe_float(row.get("quoteVolume"), row.get("baseVolume")),
                    synced_at=self._parse_backfill_datetime(row.get("timestamp") or row.get("datetime")),
                )
            return result
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def _fetch_public_funding_rates(self, *, exchange_code: str, symbols: List[str]) -> Dict[str, FundingRateCacheItem]:
        if exchange_code == "bitget":
            return self._fetch_bitget_swap_funding_rates(symbols)
        if exchange_code == "gate":
            return self._fetch_gate_swap_funding_rates(symbols)
        if exchange_code == "okx":
            return self._fetch_okx_swap_funding_rates(symbols)
        if exchange_code == "binance":
            return self._fetch_binance_swap_funding_rates(symbols)
        exchange = self._build_public_exchange(exchange_code=exchange_code, market_type="swap")
        try:
            if not exchange.has.get("fetchFundingRates"):
                return {}
            payload = exchange.fetch_funding_rates(symbols)
            result: Dict[str, FundingRateCacheItem] = {}
            for symbol, item in payload.items():
                row = item or {}
                normalized_symbol = str(row.get("symbol") or symbol or "")
                next_funding_timestamp = row.get("nextFundingTimestamp")
                next_funding_at = (
                    datetime.fromtimestamp(next_funding_timestamp / 1000)
                    if next_funding_timestamp
                    else None
                )
                result[normalized_symbol] = FundingRateCacheItem(
                    exchange_code=exchange_code,
                    symbol=normalized_symbol,
                    funding_rate_percent=float(row.get("fundingRate") or 0) * 100,
                    next_funding_at=next_funding_at,
                    synced_at=datetime.now(),
                    settlement_interval_hours=self._resolve_funding_interval_hours(
                        exchange_code=exchange_code,
                        payload=row,
                        next_funding_at=next_funding_at,
                    ),
                )
            return result
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def _fetch_bitget_swap_funding_rates(self, symbols: List[str]) -> Dict[str, FundingRateCacheItem]:
        if not symbols:
            return {}
        last_error: Exception | None = None
        for attempt in range(1, self._backfill_bitget_retry_attempts + 1):
            try:
                payload = self._http_get_json(
                    "https://api.bitget.com/api/v2/mix/market/current-fund-rate",
                    params={"productType": "USDT-FUTURES"},
                )
                rows = payload.get("data") if isinstance(payload, dict) else []
                if not isinstance(rows, list):
                    return {}
                target_symbols = set(symbols)
                result: Dict[str, FundingRateCacheItem] = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    symbol = self._normalize_rest_symbol("bitget", str(row.get("symbol") or row.get("instId") or ""))
                    if not symbol or symbol not in target_symbols:
                        continue
                    next_funding_at = self._parse_ws_datetime(row.get("nextUpdate")) if row.get("nextUpdate") else None
                    result[symbol] = FundingRateCacheItem(
                        exchange_code="bitget",
                        symbol=symbol,
                        funding_rate_percent=self._safe_float(row.get("fundingRate")) * 100,
                        next_funding_at=next_funding_at,
                        synced_at=self._parse_backfill_datetime(row.get("ts")),
                        settlement_interval_hours=self._resolve_funding_interval_hours(
                            exchange_code="bitget",
                            payload=row,
                            next_funding_at=next_funding_at,
                        ),
                    )
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self._backfill_bitget_retry_attempts:
                    break
                time.sleep(self._backfill_bitget_retry_delay_seconds)
        if last_error is not None:
            raise last_error
        return {}

    def _fetch_gate_swap_funding_rates(self, symbols: List[str]) -> Dict[str, FundingRateCacheItem]:
        if not symbols:
            return {}
        payload = self._http_get_json(
            "https://api.gateio.ws/api/v4/futures/usdt/contracts",
        )
        rows = payload if isinstance(payload, list) else []
        target_symbols = set(symbols)
        result: Dict[str, FundingRateCacheItem] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = self._normalize_rest_symbol("gate", str(row.get("name") or row.get("contract") or ""))
            if not symbol or symbol not in target_symbols:
                continue
            next_funding_at = self._parse_backfill_datetime(row.get("funding_next_apply")) if row.get("funding_next_apply") else None
            result[symbol] = FundingRateCacheItem(
                exchange_code="gate",
                symbol=symbol,
                funding_rate_percent=self._safe_float(row.get("funding_rate")) * 100,
                next_funding_at=next_funding_at,
                synced_at=datetime.now(),
                settlement_interval_hours=self._resolve_funding_interval_hours(
                    exchange_code="gate",
                    payload=row,
                    next_funding_at=next_funding_at,
                ),
            )
        return result

    def _fetch_okx_swap_funding_rates(self, symbols: List[str]) -> Dict[str, FundingRateCacheItem]:
        if not symbols:
            return {}
        exchange = self._build_public_exchange(exchange_code="okx", market_type="swap")
        try:
            if not exchange.has.get("fetchFundingRates"):
                return {}
            rows = exchange.fetch_funding_rates(symbols)
        finally:
            try:
                exchange.close()
            except Exception:
                pass
        result: Dict[str, FundingRateCacheItem] = {}
        for symbol, item in rows.items():
            row = item or {}
            normalized_symbol = str(row.get("symbol") or symbol or "")
            if not normalized_symbol:
                continue
            next_funding_timestamp = row.get("nextFundingTimestamp")
            next_funding_at = (
                datetime.fromtimestamp(next_funding_timestamp / 1000)
                if next_funding_timestamp
                else None
            )
            result[normalized_symbol] = FundingRateCacheItem(
                exchange_code="okx",
                symbol=normalized_symbol,
                funding_rate_percent=float(row.get("fundingRate") or 0) * 100,
                next_funding_at=next_funding_at,
                synced_at=datetime.now(),
                settlement_interval_hours=self._resolve_funding_interval_hours(
                    exchange_code="okx",
                    payload=row,
                    next_funding_at=next_funding_at,
                ),
            )
        return result

    def _fetch_binance_swap_funding_rates(self, symbols: List[str]) -> Dict[str, FundingRateCacheItem]:
        if not symbols:
            return {}
        payload = self._http_get_json("https://fapi.binance.com/fapi/v1/premiumIndex")
        rows = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
        target_symbols = set(symbols)
        result: Dict[str, FundingRateCacheItem] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = self._normalize_rest_symbol("binance", str(row.get("symbol") or ""))
            if not symbol or symbol not in target_symbols:
                continue
            next_funding_at = self._parse_ws_datetime(row.get("nextFundingTime")) if row.get("nextFundingTime") else None
            result[symbol] = FundingRateCacheItem(
                exchange_code="binance",
                symbol=symbol,
                funding_rate_percent=self._safe_float(row.get("lastFundingRate")) * 100,
                next_funding_at=next_funding_at,
                synced_at=datetime.now(),
                settlement_interval_hours=self._resolve_funding_interval_hours(
                    exchange_code="binance",
                    payload=row,
                    next_funding_at=next_funding_at,
                ),
            )
        return result

    def _fetch_public_funding_rate(self, *, exchange_code: str, symbol: str) -> FundingRateCacheItem | None:
        exchange = self._build_public_exchange(exchange_code=exchange_code, market_type="swap")
        try:
            if not exchange.has.get("fetchFundingRate"):
                return None
            payload = exchange.fetch_funding_rate(symbol)
            next_funding_timestamp = payload.get("nextFundingTimestamp")
            next_funding_at = (
                datetime.fromtimestamp(next_funding_timestamp / 1000)
                if next_funding_timestamp
                else None
            )
            funding_rate = float(payload.get("fundingRate") or 0) * 100
            return FundingRateCacheItem(
                exchange_code=exchange_code,
                symbol=symbol,
                funding_rate_percent=funding_rate,
                next_funding_at=next_funding_at,
                synced_at=datetime.now(),
                settlement_interval_hours=self._resolve_funding_interval_hours(
                    exchange_code=exchange_code,
                    payload=payload,
                    next_funding_at=next_funding_at,
                ),
            )
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def _format_ticker_samples(self, batch: Dict[str, TickerCacheItem], *, limit: int = 3) -> str:
        if not batch:
            return " | 样例: 无"
        parts: List[str] = []
        for symbol in sorted(batch.keys())[:limit]:
            item = batch[symbol]
            parts.append(
                f"{symbol} last={item.last_price:.8f} bid={item.bid_price:.8f} ask={item.ask_price:.8f}"
            )
        return " | 样例: " + " ; ".join(parts)

    def _format_funding_samples(self, batch: Dict[str, FundingRateCacheItem], *, limit: int = 3) -> str:
        if not batch:
            return " | 样例: 无"
        parts: List[str] = []
        for symbol in sorted(batch.keys())[:limit]:
            item = batch[symbol]
            next_funding_at = (
                item.next_funding_at.strftime("%Y-%m-%d %H:%M:%S")
                if item.next_funding_at is not None
                else "--"
            )
            parts.append(
                f"{symbol} rate={item.funding_rate_percent:.6f}% next={next_funding_at}"
            )
        return " | 样例: " + " ; ".join(parts)

    def _resolve_funding_interval_hours(
        self,
        *,
        exchange_code: str,
        payload: Dict[str, object] | None,
        next_funding_at: datetime | None,
    ) -> float:
        row = payload or {}

        for candidate in (
            row.get("fundingIntervalHours"),
            row.get("funding_interval_hours"),
            row.get("fundingInterval"),
            row.get("funding_interval"),
        ):
            interval_hours = self._safe_float(candidate)
            if interval_hours > 0:
                return interval_hours

        if exchange_code == "gate":
            interval_seconds = self._safe_float(
                row.get("funding_interval"),
                row.get("funding_interval_seconds"),
            )
            if interval_seconds > 0:
                return interval_seconds / 3600

        if exchange_code == "bitget":
            interval_hours = self._safe_float(row.get("fundInterval"))
            if interval_hours > 0:
                return interval_hours
            return 8.0

        if exchange_code in {"binance", "okx"}:
            return 8.0

        if next_funding_at is not None:
            remaining_seconds = (next_funding_at - datetime.now()).total_seconds()
            if remaining_seconds > 0:
                estimated_hours = remaining_seconds / 3600
                if estimated_hours <= 4.5:
                    return 4.0
                if estimated_hours <= 8.5:
                    return 8.0
                if estimated_hours <= 12.5:
                    return 12.0
                return round(estimated_hours)

        return 8.0

    def _build_ticker_from_values(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbol: str,
        last_price: float,
        bid_price: float,
        ask_price: float,
        quote_volume: float,
        synced_at,
    ) -> TickerCacheItem | None:
        fallback_last_price = max(float(last_price or 0), float(bid_price or 0), float(ask_price or 0))
        if fallback_last_price <= 0:
            return None
        return TickerCacheItem(
            exchange_code=exchange_code,
            market_type=market_type,
            symbol=symbol,
            last_price=fallback_last_price,
            bid_price=float(bid_price or 0) if float(bid_price or 0) > 0 else fallback_last_price,
            ask_price=float(ask_price or 0) if float(ask_price or 0) > 0 else fallback_last_price,
            quote_volume=float(quote_volume or 0),
            synced_at=self._parse_backfill_datetime(synced_at),
        )

    def _http_get_json(self, url: str, *, params: Dict[str, object] | None = None):
        query = urlencode({key: value for key, value in (params or {}).items() if value not in (None, "")})
        final_url = f"{url}?{query}" if query else url
        request = Request(
            final_url,
            headers={
                "User-Agent": "ArbiMatrix/1.0",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
        return json.loads(body)

    def _normalize_rest_symbol(self, exchange_code: str, raw_symbol: str) -> str:
        normalized = str(raw_symbol or "").strip().upper()
        if not normalized:
            return ""
        if exchange_code == "bitget":
            base = normalized[:-4] if normalized.endswith("USDT") else normalized
            return f"{base}/USDT:USDT" if base else ""
        if exchange_code == "gate":
            base = normalized.replace("_", "/")
            if not base.endswith("/USDT"):
                return ""
            return f"{base}:USDT"
        if exchange_code == "okx":
            if not normalized.endswith("-SWAP"):
                return ""
            base = normalized[:-5].replace("-", "/")
            if not base.endswith("/USDT"):
                return ""
            return f"{base}:USDT"
        if exchange_code == "binance":
            base = normalized[:-4] if normalized.endswith("USDT") else normalized
            return f"{base}/USDT:USDT" if base else ""
        return normalized

    def _build_public_exchange(self, *, exchange_code: str, market_type: str):
        exchange_class_name = self._resolve_exchange_class_name(exchange_code=exchange_code, market_type=market_type)
        exchange_class = getattr(ccxt, exchange_class_name)
        params = {
            "enableRateLimit": True,
            "timeout": max(1000, int(self._backfill_request_timeout_seconds * 1000)),
            "options": {
                "defaultType": self._resolve_default_type(exchange_code=exchange_code, market_type=market_type),
            },
        }
        if exchange_code == "okx":
            params["options"]["fetchMarkets"] = {"types": [self._resolve_okx_market_fetch_type(market_type)]}
        exchange = exchange_class(params)
        try:
            exchange.session.trust_env = False
        except Exception:
            pass
        return exchange

    def _resolve_exchange_class_name(self, *, exchange_code: str, market_type: str) -> str:
        if exchange_code == "binance" and market_type == "swap":
            return "binanceusdm"
        return exchange_code

    def _resolve_default_type(self, *, exchange_code: str, market_type: str) -> str:
        if exchange_code == "binance" and market_type == "swap":
            return "swap"
        return market_type

    def _resolve_okx_market_fetch_type(self, market_type: str) -> str:
        if market_type == "swap":
            return "swap"
        return "spot"

    def _to_ws_symbol(self, exchange_code: str, symbol: str) -> str:
        normalized = str(symbol or "").strip()
        if not normalized:
            return ""
        if exchange_code == "bitget":
            return normalized.replace("/", "").replace(":USDT", "")
        if exchange_code == "gate":
            return normalized.replace("/", "_").replace(":USDT", "")
        if exchange_code == "okx":
            return normalized.replace("/", "-").replace(":USDT", "-SWAP")
        if exchange_code == "binance":
            return normalized.replace("/", "").replace(":USDT", "")
        return normalized

    def _parse_json(self, text: str) -> dict | list | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _safe_float(self, *values) -> float:
        for value in values:
            try:
                result = float(value)
            except (TypeError, ValueError):
                continue
            if result == result:
                return result
        return 0.0

    def _parse_ws_datetime(self, value) -> datetime:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return datetime.now()
        if numeric > 10_000_000_000:
            return datetime.fromtimestamp(numeric / 1000)
        if numeric > 0:
            return datetime.fromtimestamp(numeric)
        return datetime.now()

    def _parse_backfill_datetime(self, value) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return datetime.now()
        return self._parse_ws_datetime(value)

    def _run_backfill_loop(self) -> None:
        next_dispatch_monotonic = time.monotonic()
        last_heartbeat_monotonic = 0.0
        while True:
            try:
                self._collect_completed_backfill_tasks()
                current_monotonic = time.monotonic()
                if current_monotonic - last_heartbeat_monotonic >= self._backfill_heartbeat_interval_seconds:
                    monitor_center_service.heartbeat(
                        self._backfill_monitor_key,
                        status="running",
                        detail=self._build_backfill_monitor_detail(),
                    )
                    last_heartbeat_monotonic = current_monotonic

                if current_monotonic >= next_dispatch_monotonic:
                    self._dispatch_backfill_round()
                    while next_dispatch_monotonic <= current_monotonic:
                        next_dispatch_monotonic += self._backfill_schedule_interval_seconds
            except Exception as exc:  # noqa: BLE001
                logger.warning("Backfill side loop failed: %s", exc)
                monitor_center_service.mark_error(
                    self._backfill_monitor_key,
                    f"行情回补异常: {exc}",
                )
                monitor_center_service.add_log(
                    self._backfill_monitor_key,
                    "warning",
                    f"行情回补异常: {exc}",
                )
            time.sleep(0.5)

    def _dispatch_backfill_round(self) -> None:
        if self._enable_catalog_sync:
            self._try_market_catalog_sync()

        targets = self._collect_backfill_targets()
        specs = self._build_backfill_task_specs(targets)
        if not specs:
            monitor_center_service.add_log(
                self._backfill_monitor_key,
                "warning",
                "行情补位本轮没有可用的永续合约目标，已跳过调度",
            )
            return

        self._backfill_round_id += 1
        round_id = self._backfill_round_id
        dispatched_count = 0
        skipped_count = 0
        now = datetime.now()

        with self._backfill_state_lock:
            for spec in specs:
                existing_future = self._backfill_futures.get(spec.task_key)
                if existing_future is not None and not existing_future.done():
                    skipped_count += 1
                    continue

                state = self._ensure_backfill_task_state(spec)
                state.symbol_count = len(spec.symbols)
                state.is_running = True
                state.last_started_at = now
                state.last_finished_at = None
                state.last_error_message = ""
                state.last_round_id = round_id
                future = self._backfill_executor.submit(self._run_backfill_task, spec)
                self._backfill_futures[spec.task_key] = future
                dispatched_count += 1

        monitor_center_service.add_log(
            self._backfill_monitor_key,
            "info",
            (
                f"补位第 {round_id} 轮已调度 {dispatched_count}/{len(specs)} 个任务"
                + (f"，跳过 {skipped_count} 个仍在运行中的任务" if skipped_count > 0 else "")
            ),
        )

    def _build_backfill_task_specs(self, targets: List[WatchTarget]) -> List[BackfillTaskSpec]:
        ticker_groups: Dict[tuple[str, str], List[str]] = {}
        funding_groups: Dict[str, List[str]] = {}

        for item in targets:
            ticker_groups.setdefault((item.exchange_code, item.market_type), []).append(str(item.symbol))
            if item.market_type == "swap":
                funding_groups.setdefault(item.exchange_code, []).append(str(item.symbol))

        specs: List[BackfillTaskSpec] = []
        if self._enable_http_ticker_backfill:
            for (exchange_code, market_type), symbols in sorted(ticker_groups.items()):
                ordered_symbols = self._sort_symbols_by_backfill_priority(
                    exchange_code=exchange_code,
                    market_type=market_type,
                    task_type="ticker",
                    symbols=symbols,
                )
                chunk_size = self._resolve_backfill_chunk_size(
                    exchange_code=exchange_code,
                    task_type="ticker",
                )
                chunks = self._chunk_symbols(ordered_symbols, chunk_size)
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
        if self._enable_http_funding_backfill:
            for exchange_code, symbols in sorted(funding_groups.items()):
                ordered_symbols = self._sort_symbols_by_backfill_priority(
                    exchange_code=exchange_code,
                    market_type="swap",
                    task_type="funding",
                    symbols=symbols,
                )
                chunk_size = self._resolve_backfill_chunk_size(
                    exchange_code=exchange_code,
                    task_type="funding",
                )
                chunks = self._chunk_symbols(ordered_symbols, chunk_size)
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

    def _run_backfill_task(self, spec: BackfillTaskSpec) -> Dict[str, int | str]:
        started_monotonic = time.monotonic()
        if spec.task_type == "ticker":
            result = self._refresh_exchange_tickers(
                exchange_code=spec.exchange_code,
                market_type=spec.market_type,
                symbols=list(spec.symbols),
            )
        else:
            result = self._refresh_exchange_funding_rates(
                exchange_code=spec.exchange_code,
                symbols=list(spec.symbols),
            )
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        return {
            **result,
            "duration_ms": duration_ms,
            "task_key": spec.task_key,
            "task_type": spec.task_type,
            "exchange_code": spec.exchange_code,
            "chunk_index": spec.chunk_index,
            "chunk_total": spec.chunk_total,
        }

    def _resolve_backfill_chunk_size(self, *, exchange_code: str, task_type: str) -> int:
        normalized_exchange_code = str(exchange_code or "").strip().lower()
        normalized_task_type = str(task_type or "").strip().lower()
        if normalized_task_type == "ticker":
            if normalized_exchange_code == "bitget":
                return self._backfill_bitget_ticker_chunk_size
            return self._backfill_ticker_chunk_size
        if normalized_exchange_code == "bitget":
            return self._backfill_bitget_funding_chunk_size
        return self._backfill_funding_chunk_size

    def _sort_symbols_by_backfill_priority(
        self,
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

    def _collect_completed_backfill_tasks(self) -> None:
        completed: List[tuple[str, concurrent.futures.Future]] = []
        with self._backfill_state_lock:
            for task_key, future in list(self._backfill_futures.items()):
                if future.done():
                    completed.append((task_key, future))
                    self._backfill_futures.pop(task_key, None)

        for task_key, future in completed:
            state = self._backfill_task_states.get(task_key)
            now = datetime.now()
            if state is None:
                continue
            state.is_running = False
            state.last_finished_at = now
            try:
                result = future.result()
                state.last_duration_ms = int(result.get("duration_ms") or 0)
                state.last_success_count = int(result.get("success_count") or 0)
                state.last_missing_count = int(result.get("missing_count") or 0)
                state.last_success_at = now
                state.last_error_message = ""
            except Exception as exc:  # noqa: BLE001
                state.last_duration_ms = 0
                state.last_error_at = now
                state.last_error_message = str(exc)
                monitor_center_service.add_log(
                    self._backfill_monitor_key,
                    "warning",
                    f"{task_key} 补位任务执行异常: {exc}",
                )

    def _ensure_backfill_task_state(self, spec: BackfillTaskSpec) -> BackfillTaskState:
        state = self._backfill_task_states.get(spec.task_key)
        if state is not None:
            return state
        state = BackfillTaskState(
            task_key=spec.task_key,
            exchange_code=spec.exchange_code,
            market_type=spec.market_type,
            task_type=spec.task_type,
        )
        self._backfill_task_states[spec.task_key] = state
        return state

    def _build_backfill_monitor_detail(self) -> str:
        with self._backfill_state_lock:
            states = list(self._backfill_task_states.values())
        if not states:
            return "行情补位线程已启动，等待首轮调度"

        running_count = sum(1 for item in states if item.is_running)
        success_count = sum(1 for item in states if item.last_success_at is not None)
        samples: List[str] = []
        for item in sorted(states, key=lambda row: (row.exchange_code, row.task_type))[:4]:
            samples.append(f"{item.exchange_code}-{item.task_type}:{item.last_success_count}/{item.symbol_count}")
        sample_text = " | ".join(samples) if samples else "暂无样例"
        return f"补位轮次 {self._backfill_round_id}，运行中 {running_count}，最近成功任务 {success_count}，{sample_text}"

    def _refresh_exchange_tickers(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbols: List[str],
    ) -> Dict[str, int | str]:
        unique_symbols = sorted(set(str(item) for item in symbols if str(item)))
        if not unique_symbols:
            return {"success_count": 0, "missing_count": 0}

        batch = self._fetch_public_tickers(
            exchange_code=exchange_code,
            market_type=market_type,
            symbols=unique_symbols,
        )
        for symbol, ticker_data in batch.items():
            if symbol not in unique_symbols:
                continue
            market_runtime_cache.set_ticker(ticker_data)

        success_count = len(batch)
        missing_count = max(0, len(unique_symbols) - success_count)
        monitor_center_service.add_log(
            self._backfill_monitor_key,
            "info",
            (
                f"{exchange_code} Ticker 回补 {success_count}/{len(unique_symbols)} 条"
                + self._format_ticker_samples(batch)
            ),
        )
        if missing_count > 0:
            monitor_center_service.add_log(
                self._backfill_monitor_key,
                "warning",
                f"{exchange_code} Ticker 批量返回缺失 {missing_count} 条",
            )
        return {"success_count": success_count, "missing_count": missing_count}

    def _refresh_exchange_funding_rates(
        self,
        *,
        exchange_code: str,
        symbols: List[str],
    ) -> Dict[str, int | str]:
        unique_symbols = sorted(set(str(item) for item in symbols if str(item)))
        if not unique_symbols:
            return {"success_count": 0, "missing_count": 0}

        batch = self._fetch_public_funding_rates(
            exchange_code=exchange_code,
            symbols=unique_symbols,
        )
        for symbol, funding_data in batch.items():
            if symbol not in unique_symbols:
                continue
            market_runtime_cache.set_funding_rate(funding_data)

        success_count = len(batch)
        missing_count = max(0, len(unique_symbols) - success_count)
        monitor_center_service.add_log(
            self._backfill_monitor_key,
            "info",
            (
                f"{exchange_code} 资金费回补 {success_count}/{len(unique_symbols)} 条"
                + self._format_funding_samples(batch)
            ),
        )
        if missing_count > 0:
            monitor_center_service.add_log(
                self._backfill_monitor_key,
                "warning",
                f"{exchange_code} 资金费批量返回缺失 {missing_count} 条",
            )
        return {"success_count": success_count, "missing_count": missing_count}

    def _http_get_json(self, url: str, *, params: Dict[str, object] | None = None):
        query = urlencode({key: value for key, value in (params or {}).items() if value not in (None, "")})
        final_url = f"{url}?{query}" if query else url
        request = Request(
            final_url,
            headers={
                "User-Agent": "ArbiMatrix/1.0",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urlopen(request, timeout=self._backfill_request_timeout_seconds) as response:
            body = response.read().decode("utf-8")
        return json.loads(body)


market_data_monitor_service = MarketDataMonitorService()


__all__ = [
    "MarketDataMonitorService",
    "market_data_monitor_service",
]
