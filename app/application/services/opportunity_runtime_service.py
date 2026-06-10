"""Background runtime service for public market snapshots and user opportunity rows."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

import ccxt

from app.application.services.account_service import account_service
from app.application.services.monitor_center_service import monitor_center_service
from app.application.services.system_exchange_config_service import system_exchange_config_service
from app.infrastructure.cache import FundingRateCacheItem, TickerCacheItem, market_runtime_cache
from app.infrastructure.persistence.account_repository import account_repository
from app.infrastructure.persistence.market_repository import market_repository
from app.shared.utils.formatters import format_countdown, format_percent, format_signed_percent, format_usd_compact


logger = logging.getLogger(__name__)


class OpportunityRuntimeService:
    def __init__(self) -> None:
        self._started = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._interval_seconds = 60
        self._monitor_key = "opportunity_runtime_sync"
        self._last_market_sync_date = ""
        self._last_market_sync_success = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            monitor_center_service.register_worker(
                key=self._monitor_key,
                name="套利机会同步线程",
                category="市场监控",
                thread_name="opportunity-runtime-monitor",
                interval_seconds=self._interval_seconds,
                status="starting",
                detail="准备同步市场、配对与套利机会数据",
            )
            self._thread = threading.Thread(
                target=self._run_loop,
                name="opportunity-runtime-monitor",
                daemon=True,
            )
            self._thread.start()

    def _run_loop(self) -> None:
        while True:
            try:
                monitor_center_service.heartbeat(
                    self._monitor_key,
                    status="running",
                    detail="线程心跳正常，准备刷新市场与机会缓存",
                )
                self._ensure_daily_market_sync()
                self._refresh_public_market_runtime()
                self._refresh_user_opportunity_rows()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Opportunity runtime refresh failed: %s", exc)
                monitor_center_service.mark_error(self._monitor_key, f"套利机会同步异常: {exc}")
            time.sleep(self._interval_seconds)

    def _ensure_daily_market_sync(self) -> None:
        today_key = datetime.now().strftime("%Y-%m-%d")
        if self._last_market_sync_date == today_key and self._last_market_sync_success:
            return

        from app.application.services.market_sync_service import market_sync_service

        result = market_sync_service.sync_all_public_markets()
        self._last_market_sync_date = today_key
        self._last_market_sync_success = bool(
            result["market_count"] > 0
            or result["funding_pair_count"] > 0
            or result["spread_pair_count"] > 0
        )
        monitor_center_service.mark_success(
            self._monitor_key,
            (
                f"市场与配对已同步：市场 {result['market_count']} 条，"
                f"资金费配对 {result['funding_pair_count']} 条，"
                f"价差配对 {result['spread_pair_count']} 条"
            ),
        )

    def _refresh_public_market_runtime(self) -> None:
        active_pairs = market_repository.list_active_pairs()
        watch_targets: Dict[Tuple[str, str, str], Dict[str, str]] = {}

        for pair in active_pairs:
            left_key = (
                str(pair["left_exchange_code"]),
                str(pair["left_market_type"]),
                str(pair["left_symbol"]),
            )
            right_key = (
                str(pair["right_exchange_code"]),
                str(pair["right_market_type"]),
                str(pair["right_symbol"]),
            )
            watch_targets[left_key] = {
                "exchange_code": left_key[0],
                "market_type": left_key[1],
                "symbol": left_key[2],
                "symbol_normalized": str(pair["symbol_normalized"]),
            }
            watch_targets[right_key] = {
                "exchange_code": right_key[0],
                "market_type": right_key[1],
                "symbol": right_key[2],
                "symbol_normalized": str(pair["symbol_normalized"]),
            }

        refreshed_count = 0
        funding_count = 0
        for item in watch_targets.values():
            try:
                ticker_data = self._fetch_public_ticker(
                    exchange_code=item["exchange_code"],
                    market_type=item["market_type"],
                    symbol=item["symbol"],
                )
                market_runtime_cache.set_ticker(ticker_data)
                refreshed_count += 1

                if item["market_type"] == "swap":
                    funding_data = self._fetch_public_funding_rate(
                        exchange_code=item["exchange_code"],
                        symbol=item["symbol"],
                    )
                    if funding_data is not None:
                        market_runtime_cache.set_funding_rate(funding_data)
                        funding_count += 1
            except Exception as exc:  # noqa: BLE001
                monitor_center_service.add_log(
                    self._monitor_key,
                    "warning",
                    f"{item['exchange_code']} {item['symbol']} 行情刷新失败: {exc}",
                )

        if watch_targets:
            monitor_center_service.add_log(
                self._monitor_key,
                "info",
                f"公共行情已刷新 {refreshed_count} 个 ticker，{funding_count} 个 funding rate",
            )

    def _refresh_user_opportunity_rows(self) -> None:
        all_accounts = account_repository.list_all_accounts_with_address()
        user_ids = sorted({int(row["user_id"]) for row in all_accounts})

        for stale_user_id in market_runtime_cache.list_user_ids("funding"):
            if stale_user_id not in user_ids:
                market_runtime_cache.clear_user_rows("funding", stale_user_id)
        for stale_user_id in market_runtime_cache.list_user_ids("spread"):
            if stale_user_id not in user_ids:
                market_runtime_cache.clear_user_rows("spread", stale_user_id)

        for user_id in user_ids:
            account_rows = account_service.build_account_rows_for_user(user_id)
            strategy_rows = account_repository.list_strategy_rules_by_user_id(user_id)
            funding_rows = self._build_funding_rows_for_user(account_rows, strategy_rows)
            spread_rows = self._build_spread_rows_for_user(account_rows, strategy_rows)
            market_runtime_cache.set_user_rows("funding", user_id, funding_rows)
            market_runtime_cache.set_user_rows("spread", user_id, spread_rows)

        monitor_center_service.mark_success(
            self._monitor_key,
            f"已刷新 {len(user_ids)} 个用户的套利机会缓存",
        )

    def _build_funding_rows_for_user(
        self,
        account_rows: List[Dict[str, Any]],
        strategy_rows: List[Dict[str, Any]],
    ) -> List[dict]:
        enabled_rules = [
            row
            for row in strategy_rows
            if str(row.get("strategy_type") or "") == "funding" and bool(row.get("is_enabled"))
        ]
        if not enabled_rules:
            return []

        threshold = min((float(row.get("annualized_rate_threshold") or 0) for row in enabled_rules), default=0)
        max_spread_limit = max(
            (float(row.get("max_spread_rate_threshold") or 0) for row in enabled_rules),
            default=0,
        )
        max_pairs = max((int(row.get("max_pairs") or 0) for row in enabled_rules), default=20)

        account_map = self._build_account_lookup(account_rows)
        pair_rows = market_repository.list_active_pairs(pair_type="funding")
        result: List[dict] = []

        for pair in pair_rows:
            left_account = account_map.get((str(pair["left_exchange_code"]), "swap"))
            right_account = account_map.get((str(pair["right_exchange_code"]), "swap"))
            if left_account is None or right_account is None:
                continue

            left_ticker = market_runtime_cache.get_ticker(
                str(pair["left_exchange_code"]),
                "swap",
                str(pair["left_symbol"]),
            )
            right_ticker = market_runtime_cache.get_ticker(
                str(pair["right_exchange_code"]),
                "swap",
                str(pair["right_symbol"]),
            )
            left_funding = market_runtime_cache.get_funding_rate(
                str(pair["left_exchange_code"]),
                str(pair["left_symbol"]),
            )
            right_funding = market_runtime_cache.get_funding_rate(
                str(pair["right_exchange_code"]),
                str(pair["right_symbol"]),
            )
            if left_ticker is None or right_ticker is None or left_funding is None or right_funding is None:
                continue

            annualized = (left_funding.funding_rate_percent - right_funding.funding_rate_percent) * 3 * 365
            spread_percent = self._calc_spread_percent(left_ticker.last_price, right_ticker.last_price)

            if threshold > 0 and annualized < threshold:
                continue
            if max_spread_limit > 0 and abs(spread_percent) > max_spread_limit:
                continue

            left_available = float(left_account.get("current_available_amount") or 0)
            right_available = float(right_account.get("current_available_amount") or 0)
            qty_left = self._estimate_quantity(left_available, left_ticker.last_price)
            qty_right = self._estimate_quantity(right_available, right_ticker.last_price)
            if qty_left <= 0 and qty_right <= 0:
                continue

            next_funding_at = left_funding.next_funding_at or right_funding.next_funding_at
            settlement = self._format_remaining(next_funding_at)

            result.append(
                {
                    "rank_sort": annualized,
                    "symbol": str(pair["base_asset"]),
                    "long_exchange": self._exchange_label(str(pair["left_exchange_code"])),
                    "short_exchange": self._exchange_label(str(pair["right_exchange_code"])),
                    "annual": format_percent(annualized, 2),
                    "net_rate": format_percent(
                        left_funding.funding_rate_percent - right_funding.funding_rate_percent,
                        4,
                    ),
                    "spread": format_signed_percent(spread_percent, 2),
                    "long_fee_rate": self._resolve_fee_rate_display(left_account),
                    "short_fee_rate": self._resolve_fee_rate_display(right_account),
                    "qty_long": self._format_quantity(qty_left, str(pair["base_asset"])),
                    "qty_short": self._format_quantity(qty_right, str(pair["base_asset"])),
                    "avg_long": self._format_price(left_ticker.last_price),
                    "avg_short": self._format_price(right_ticker.last_price),
                    "value_long": format_usd_compact(qty_left * left_ticker.last_price),
                    "value_short": format_usd_compact(qty_right * right_ticker.last_price),
                    "settlement": settlement,
                }
            )

        ordered = sorted(result, key=lambda item: item["rank_sort"], reverse=True)[:max_pairs]
        for index, row in enumerate(ordered, start=1):
            row["rank"] = index
            row.pop("rank_sort", None)
        return ordered

    def _build_spread_rows_for_user(
        self,
        account_rows: List[Dict[str, Any]],
        strategy_rows: List[Dict[str, Any]],
    ) -> List[dict]:
        enabled_rules = [
            row
            for row in strategy_rows
            if str(row.get("strategy_type") or "") == "spread" and bool(row.get("is_enabled"))
        ]
        if not enabled_rules:
            return []

        threshold = min((float(row.get("spread_rate_threshold") or 0) for row in enabled_rules), default=0)
        max_spread_limit = max(
            (float(row.get("max_spread_rate_threshold") or 0) for row in enabled_rules),
            default=0,
        )
        max_pairs = max((int(row.get("max_pairs") or 0) for row in enabled_rules), default=20)

        account_map = self._build_account_lookup(account_rows)
        pair_rows = market_repository.list_active_pairs(pair_type="spread")
        result: List[dict] = []

        for pair in pair_rows:
            left_market_type = str(pair["left_market_type"])
            right_market_type = str(pair["right_market_type"])
            left_account = account_map.get((str(pair["left_exchange_code"]), left_market_type))
            right_account = account_map.get((str(pair["right_exchange_code"]), right_market_type))
            if left_account is None or right_account is None:
                continue

            left_ticker = market_runtime_cache.get_ticker(
                str(pair["left_exchange_code"]),
                left_market_type,
                str(pair["left_symbol"]),
            )
            right_ticker = market_runtime_cache.get_ticker(
                str(pair["right_exchange_code"]),
                right_market_type,
                str(pair["right_symbol"]),
            )
            if left_ticker is None or right_ticker is None:
                continue
            if left_ticker.ask_price <= 0 or right_ticker.bid_price <= 0:
                continue

            latest_spread = ((right_ticker.bid_price - left_ticker.ask_price) / left_ticker.ask_price) * 100
            if threshold > 0 and latest_spread < threshold:
                continue
            if max_spread_limit > 0 and latest_spread > max_spread_limit:
                continue

            left_fee = self._resolve_fee_rate_value(left_account)
            right_fee = self._resolve_fee_rate_value(right_account)
            net_spread = latest_spread - left_fee - right_fee

            left_available = float(left_account.get("current_available_amount") or 0)
            right_available = float(right_account.get("current_available_amount") or 0)
            qty_left = self._estimate_quantity(left_available, left_ticker.ask_price)
            qty_right = self._estimate_quantity(right_available, right_ticker.bid_price)
            if qty_left <= 0 and qty_right <= 0:
                continue

            result.append(
                {
                    "rank_sort": net_spread,
                    "symbol": str(pair["base_asset"]),
                    "buy_exchange": self._exchange_label(str(pair["left_exchange_code"])),
                    "sell_exchange": self._exchange_label(str(pair["right_exchange_code"])),
                    "latest_spread": format_signed_percent(latest_spread, 2),
                    "net_spread": format_signed_percent(net_spread, 2),
                    "buy_fee_rate": self._resolve_fee_rate_display(left_account),
                    "sell_fee_rate": self._resolve_fee_rate_display(right_account),
                    "qty_long": self._format_quantity(qty_left, str(pair["base_asset"])),
                    "qty_short": self._format_quantity(qty_right, str(pair["base_asset"])),
                    "avg_long": self._format_price(left_ticker.ask_price),
                    "avg_short": self._format_price(right_ticker.bid_price),
                    "value_long": format_usd_compact(qty_left * left_ticker.ask_price),
                    "value_short": format_usd_compact(qty_right * right_ticker.bid_price),
                    "opportunity_time": self._format_datetime(left_ticker.synced_at or right_ticker.synced_at),
                }
            )

        ordered = sorted(result, key=lambda item: item["rank_sort"], reverse=True)[:max_pairs]
        for index, row in enumerate(ordered, start=1):
            row["rank"] = index
            row.pop("rank_sort", None)
        return ordered

    def _fetch_public_ticker(self, *, exchange_code: str, market_type: str, symbol: str) -> TickerCacheItem:
        exchange = self._build_public_exchange(exchange_code=exchange_code, market_type=market_type)
        try:
            ticker = exchange.fetch_ticker(symbol)
            synced_at = datetime.now()
            return TickerCacheItem(
                exchange_code=exchange_code,
                market_type=market_type,
                symbol=symbol,
                last_price=float(ticker.get("last") or ticker.get("close") or 0),
                bid_price=float(ticker.get("bid") or ticker.get("last") or 0),
                ask_price=float(ticker.get("ask") or ticker.get("last") or 0),
                quote_volume=float(ticker.get("quoteVolume") or 0),
                synced_at=synced_at,
            )
        finally:
            try:
                exchange.close()
            except Exception:
                pass

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
            )
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def _build_public_exchange(self, *, exchange_code: str, market_type: str):
        exchange_class = getattr(ccxt, exchange_code)
        params = {
            "enableRateLimit": True,
            "timeout": 10000,
            "options": {
                "defaultType": market_type,
            },
        }
        exchange = exchange_class(params)
        try:
            exchange.session.trust_env = False
        except Exception:
            pass
        return exchange

    def _build_account_lookup(self, rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
        lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for row in rows:
            market_code = self._market_code_from_label(
                str(row.get("market_type_code") or row.get("market_type") or "")
            )
            exchange_code = self._exchange_code_from_label(
                str(row.get("exchange_code") or row.get("exchange") or "")
            )
            if not market_code or not exchange_code:
                continue
            lookup[(exchange_code, market_code)] = row
        return lookup

    def _resolve_fee_rate_display(self, account_row: Dict[str, Any]) -> str:
        return f"{self._resolve_fee_rate_value(account_row):.2f}%"

    def _resolve_fee_rate_value(self, account_row: Dict[str, Any]) -> float:
        market_type = self._market_code_from_label(str(account_row.get("market_type") or ""))
        if market_type == "spot":
            return 0.10
        return 0.05

    def _estimate_quantity(self, available_amount: float, price: float) -> float:
        if available_amount <= 0 or price <= 0:
            return 0.0
        usable = min(available_amount, 1000.0)
        return usable / price

    def _calc_spread_percent(self, left_price: float, right_price: float) -> float:
        if left_price <= 0 or right_price <= 0:
            return 0.0
        return ((left_price - right_price) / right_price) * 100

    def _format_remaining(self, next_funding_at: datetime | None) -> str:
        if next_funding_at is None:
            return "--"
        seconds = int((next_funding_at - datetime.now()).total_seconds())
        return format_countdown(max(seconds, 0))

    def _format_quantity(self, quantity: float, base_asset: str) -> str:
        if quantity >= 1000:
            return f"{quantity:,.0f} {base_asset}"
        if quantity >= 1:
            return f"{quantity:,.2f} {base_asset}"
        return f"{quantity:,.4f} {base_asset}"

    def _format_price(self, price: float) -> str:
        if price >= 1000:
            return f"{price:,.0f}"
        if price >= 1:
            return f"{price:,.2f}".rstrip("0").rstrip(".")
        return f"{price:,.4f}".rstrip("0").rstrip(".")

    def _format_datetime(self, value: datetime | None) -> str:
        if value is None:
            return "--"
        return value.strftime("%H:%M:%S")

    def _market_code_from_label(self, label: str) -> str:
        mapping = {
            "现货": "spot",
            "永续合约": "swap",
            "spot": "spot",
            "swap": "swap",
        }
        return mapping.get(label, label.lower())

    def _exchange_code_from_label(self, label: str) -> str:
        mapping = {
            "Binance": "binance",
            "Bitget": "bitget",
            "OKX": "okx",
            "Gate": "gate",
            "HTX": "htx",
        }
        return mapping.get(label, label.lower())

    def _exchange_label(self, exchange_code: str) -> str:
        mapping = {
            "binance": "Binance",
            "bitget": "Bitget",
            "okx": "OKX",
            "gate": "Gate",
            "htx": "HTX",
        }
        return mapping.get(exchange_code, exchange_code.upper())


opportunity_runtime_service = OpportunityRuntimeService()
