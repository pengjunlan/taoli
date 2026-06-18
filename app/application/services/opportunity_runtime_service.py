"""Background runtime service for shared opportunity rows and per-user strategy payloads."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.application.services.market_sync_service import market_sync_service
from app.application.services.monitor_center_service import monitor_center_service
from app.application.services.opportunity_snapshot_service import opportunity_snapshot_service
from app.application.services.trade_decision_service import trade_decision_service
from app.infrastructure.cache import market_runtime_cache, strategy_runtime_cache
from app.infrastructure.persistence.account_repository import account_repository
from app.infrastructure.persistence.market_repository import market_repository
from app.shared.utils.formatters import format_countdown, format_percent, format_signed_percent


logger = logging.getLogger(__name__)


class OpportunityRuntimeService:
    def __init__(self) -> None:
        self._started = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._interval_seconds = 1
        self._market_data_execution_stale_seconds = 150
        self._market_data_display_stale_seconds = 15 * 60
        self._max_cross_exchange_price_gap_percent = 15.0
        self._monitor_key = "opportunity_runtime_sync"

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
                detail="正在准备公共套利机会运行时缓存。",
            )
            self._warm_caches_from_snapshot()
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
                    detail="正在根据实时行情刷新公共套利机会列表。",
                )
                self._refresh_runtime_rows()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Opportunity runtime refresh failed: %s", exc)
                monitor_center_service.mark_error(self._monitor_key, f"套利机会同步异常: {exc}")
            time.sleep(self._interval_seconds)

    def _warm_caches_from_snapshot(self) -> None:
        warmed_channels = opportunity_snapshot_service.warm_public_runtime_cache_from_snapshot()
        if any(warmed_channels.values()):
            monitor_center_service.add_log(
                self._monitor_key,
                "info",
                "已从快照预热公共套利机会缓存。",
            )

    def _refresh_runtime_rows(self) -> None:
        all_accounts = account_repository.list_all_accounts_with_address()
        user_ids = sorted({int(row["user_id"]) for row in all_accounts})
        enabled_exchange_codes = set(market_sync_service.list_supported_exchange_codes())
        funding_pairs = [
            row
            for row in market_repository.list_active_pairs(pair_type="funding")
            if str(row.get("left_exchange_code") or "") in enabled_exchange_codes
            and str(row.get("right_exchange_code") or "") in enabled_exchange_codes
        ]
        spread_pairs = [
            row
            for row in market_repository.list_active_pairs(pair_type="spread")
            if str(row.get("left_exchange_code") or "") in enabled_exchange_codes
            and str(row.get("right_exchange_code") or "") in enabled_exchange_codes
        ]

        for stale_user_id in strategy_runtime_cache.list_user_ids():
            if stale_user_id not in user_ids:
                strategy_runtime_cache.clear_user_payload(stale_user_id)

        generated_at = datetime.now()
        funding_rows = self._build_public_funding_rows(funding_pairs)
        spread_rows = self._build_public_spread_rows(spread_pairs)
        funding_live_rows = self._filter_live_rows(funding_rows)
        spread_live_rows = self._filter_live_rows(spread_rows)
        funding_display_rows = self._prepare_display_rows(funding_rows)
        spread_display_rows = self._prepare_display_rows(spread_rows)
        funding_ready = bool(funding_live_rows)
        spread_ready = bool(spread_live_rows)

        market_runtime_cache.set_public_rows(
            "funding",
            funding_display_rows,
            is_ready=funding_ready,
            source="runtime",
            generated_at=generated_at,
            updated_at=generated_at,
            message=(
                "资金费套利机会运行时已就绪。"
                if funding_ready
                else "资金费套利机会正在等待完整的实时价格与资金费数据。"
            ),
        )
        market_runtime_cache.set_public_rows(
            "spread",
            spread_display_rows,
            is_ready=spread_ready,
            source="runtime",
            generated_at=generated_at,
            updated_at=generated_at,
            message=(
                "价差套利机会运行时已就绪。"
                if spread_ready
                else "价差套利机会正在等待完整的实时买一卖一数据。"
            ),
        )
        opportunity_snapshot_service.persist_public_opportunity_rows(
            channel="funding",
            rows=funding_live_rows,
            generated_at=generated_at,
        )
        opportunity_snapshot_service.persist_public_opportunity_rows(
            channel="spread",
            rows=spread_live_rows,
            generated_at=generated_at,
        )

        for user_id in user_ids:
            strategy_rows = account_repository.list_strategy_rules_by_user_id(user_id)
            strategy_payload = trade_decision_service.build_runtime_payload(
                user_id=user_id,
                strategy_rows=strategy_rows,
                funding_rows=funding_live_rows,
                spread_rows=spread_live_rows,
            )
            strategy_payload["is_ready"] = funding_ready or spread_ready
            strategy_payload["source"] = "runtime"
            strategy_payload["status_message"] = "策略运行态已按最新公共套利机会刷新。"
            strategy_payload["updated_at"] = generated_at
            strategy_runtime_cache.set_user_payload(user_id, strategy_payload)
            opportunity_snapshot_service.persist_strategy_payload(user_id=user_id, payload=strategy_payload)

        monitor_center_service.mark_success(
            self._monitor_key,
            f"套利机会已刷新：资金费 {len(funding_display_rows)} 条 / 价差 {len(spread_display_rows)} 条",
        )

    def _build_public_funding_rows(self, pair_rows: List[Dict[str, Any]]) -> List[dict]:
        result: List[dict] = []

        for pair in pair_rows:
            left_exchange_code = str(pair["left_exchange_code"])
            right_exchange_code = str(pair["right_exchange_code"])

            left_ticker = market_runtime_cache.get_ticker(
                left_exchange_code,
                "swap",
                str(pair["left_symbol"]),
            )
            right_ticker = market_runtime_cache.get_ticker(
                right_exchange_code,
                "swap",
                str(pair["right_symbol"]),
            )
            left_funding = market_runtime_cache.get_funding_rate(
                left_exchange_code,
                str(pair["left_symbol"]),
            )
            right_funding = market_runtime_cache.get_funding_rate(
                right_exchange_code,
                str(pair["right_symbol"]),
            )
            has_market_data = (
                left_ticker is not None
                and right_ticker is not None
                and left_funding is not None
                and right_funding is not None
                and float(left_ticker.last_price) > 0
                and float(right_ticker.last_price) > 0
            )
            is_market_data_fresh = self._is_market_data_fresh(
                left_ticker=left_ticker,
                right_ticker=right_ticker,
                left_funding=left_funding,
                right_funding=right_funding,
            )
            is_market_data_display_ready = self._is_market_data_fresh(
                left_ticker=left_ticker,
                right_ticker=right_ticker,
                left_funding=left_funding,
                right_funding=right_funding,
                stale_seconds=self._market_data_display_stale_seconds,
            )

            funding_diff_percent = (
                left_funding.funding_rate_percent - right_funding.funding_rate_percent
                if has_market_data and left_funding is not None and right_funding is not None
                else 0.0
            )
            left_is_short_leg = funding_diff_percent >= 0
            raw_left_price_value = float(left_ticker.last_price) if left_ticker is not None else 0.0
            raw_right_price_value = float(right_ticker.last_price) if right_ticker is not None else 0.0
            left_short_right_long_net_rate = (
                left_funding.funding_rate_percent - right_funding.funding_rate_percent
                if has_market_data and left_funding is not None and right_funding is not None
                else 0.0
            )
            right_short_left_long_net_rate = (
                right_funding.funding_rate_percent - left_funding.funding_rate_percent
                if has_market_data and left_funding is not None and right_funding is not None
                else 0.0
            )
            actual_net_rate = abs(funding_diff_percent) if has_market_data else 0.0
            annualized = actual_net_rate * 3 * 365 if has_market_data else 0.0
            short_exchange_code = left_exchange_code if left_is_short_leg else right_exchange_code
            long_exchange_code = right_exchange_code if left_is_short_leg else left_exchange_code
            short_symbol_raw = str(pair["left_symbol"]) if left_is_short_leg else str(pair["right_symbol"])
            long_symbol_raw = str(pair["right_symbol"]) if left_is_short_leg else str(pair["left_symbol"])
            long_price_value = (
                float(right_ticker.last_price)
                if left_is_short_leg and right_ticker is not None
                else float(left_ticker.last_price) if left_ticker is not None else 0.0
            )
            short_price_value = (
                float(left_ticker.last_price)
                if left_is_short_leg and left_ticker is not None
                else float(right_ticker.last_price) if right_ticker is not None else 0.0
            )
            spread_percent = (
                self._calc_price_gap_percent(short_price_value, long_price_value, absolute=True)
                if has_market_data
                else 0.0
            )
            price_diff_value = abs(raw_left_price_value - raw_right_price_value) if has_market_data else 0.0
            cross_exchange_price_gap_percent = (
                self._calc_absolute_diff_percent(raw_left_price_value, raw_right_price_value)
                if has_market_data
                else 0.0
            )
            is_price_aligned = has_market_data and cross_exchange_price_gap_percent <= self._max_cross_exchange_price_gap_percent

            next_funding_at = None
            if left_funding is not None:
                next_funding_at = left_funding.next_funding_at
            if next_funding_at is None and right_funding is not None:
                next_funding_at = right_funding.next_funding_at
            settlement = self._format_remaining(next_funding_at)

            result.append(
                {
                    "rank_sort": annualized,
                    "market_pair_key": str(pair.get("pair_key") or ""),
                    "market_left_exchange_code": left_exchange_code,
                    "market_right_exchange_code": right_exchange_code,
                    "market_left_symbol_raw": str(pair["left_symbol"]),
                    "market_right_symbol_raw": str(pair["right_symbol"]),
                    "symbol": str(pair["base_asset"]),
                    "long_exchange": self._exchange_label(long_exchange_code),
                    "short_exchange": self._exchange_label(short_exchange_code),
                    "left_exchange_code": long_exchange_code,
                    "right_exchange_code": short_exchange_code,
                    "left_market_type": "swap",
                    "right_market_type": "swap",
                    "left_symbol_raw": long_symbol_raw,
                    "right_symbol_raw": short_symbol_raw,
                    "left_price_value": long_price_value,
                    "right_price_value": short_price_value,
                    "annual": format_percent(annualized, 2) if has_market_data else "--",
                    "net_rate": format_percent(actual_net_rate, 4) if has_market_data else "--",
                    "net_rate_value": actual_net_rate,
                    "annual_value": annualized,
                    "spread": format_signed_percent(spread_percent, 2) if has_market_data else "--",
                    "spread_value": spread_percent,
                    "raw_funding_diff_value": funding_diff_percent,
                    "left_long_right_short_net_rate_value": right_short_left_long_net_rate,
                    "right_long_left_short_net_rate_value": left_short_right_long_net_rate,
                    "price_diff": self._format_price(price_diff_value) if has_market_data else "--",
                    "price_diff_value": price_diff_value,
                    "long_funding_rate": (
                        format_signed_percent(
                            right_funding.funding_rate_percent if left_is_short_leg and right_funding is not None else left_funding.funding_rate_percent,
                            4,
                        )
                        if has_market_data and ((left_is_short_leg and right_funding is not None) or left_funding is not None)
                        else "--"
                    ),
                    "short_funding_rate": (
                        format_signed_percent(
                            left_funding.funding_rate_percent if left_is_short_leg and left_funding is not None else right_funding.funding_rate_percent,
                            4,
                        )
                        if has_market_data and ((left_is_short_leg and left_funding is not None) or right_funding is not None)
                        else "--"
                    ),
                    "long_fee_rate": self._resolve_fee_rate_display(market_type="swap"),
                    "short_fee_rate": self._resolve_fee_rate_display(market_type="swap"),
                    "avg_long": self._format_price(long_price_value),
                    "avg_short": self._format_price(short_price_value),
                    "settlement": settlement if has_market_data else "--",
                    "has_market_data": has_market_data,
                    "is_market_data_fresh": is_market_data_fresh,
                    "is_market_data_display_ready": is_market_data_display_ready,
                    "is_price_aligned": is_price_aligned,
                    "cross_exchange_price_gap_percent_value": cross_exchange_price_gap_percent,
                }
            )

        return self._finalize_rows(result)

    def _build_public_spread_rows(self, pair_rows: List[Dict[str, Any]]) -> List[dict]:
        result: List[dict] = []

        for pair in pair_rows:
            left_exchange_code = str(pair["left_exchange_code"])
            right_exchange_code = str(pair["right_exchange_code"])
            left_market_type = str(pair["left_market_type"])
            right_market_type = str(pair["right_market_type"])
            if left_market_type != "swap" or right_market_type != "swap":
                continue

            left_ticker = market_runtime_cache.get_ticker(
                left_exchange_code,
                left_market_type,
                str(pair["left_symbol"]),
            )
            right_ticker = market_runtime_cache.get_ticker(
                right_exchange_code,
                right_market_type,
                str(pair["right_symbol"]),
            )
            has_market_data = (
                left_ticker is not None
                and right_ticker is not None
                and left_ticker.ask_price > 0
                and left_ticker.bid_price > 0
                and right_ticker.ask_price > 0
                and right_ticker.bid_price > 0
            )
            is_market_data_fresh = self._is_market_data_fresh(
                left_ticker=left_ticker,
                right_ticker=right_ticker,
                left_funding=None,
                right_funding=None,
            )
            is_market_data_display_ready = self._is_market_data_fresh(
                left_ticker=left_ticker,
                right_ticker=right_ticker,
                left_funding=None,
                right_funding=None,
                stale_seconds=self._market_data_display_stale_seconds,
            )

            left_buy_right_sell_spread = (
                self._calc_price_gap_percent(right_ticker.bid_price, left_ticker.ask_price, absolute=True)
                if has_market_data and left_ticker is not None and right_ticker is not None and left_ticker.ask_price > 0
                else 0.0
            )
            right_buy_left_sell_spread = (
                self._calc_price_gap_percent(left_ticker.bid_price, right_ticker.ask_price, absolute=True)
                if has_market_data and left_ticker is not None and right_ticker is not None and right_ticker.ask_price > 0
                else 0.0
            )
            buy_price_value = float(left_ticker.ask_price) if left_ticker is not None else 0.0
            sell_price_value = float(right_ticker.bid_price) if right_ticker is not None else 0.0
            reverse_buy_price_value = float(right_ticker.ask_price) if right_ticker is not None else 0.0
            reverse_sell_price_value = float(left_ticker.bid_price) if left_ticker is not None else 0.0
            left_buy_right_sell_price_diff = sell_price_value - buy_price_value if has_market_data else 0.0
            right_buy_left_sell_price_diff = reverse_sell_price_value - reverse_buy_price_value if has_market_data else 0.0
            left_is_buy_leg = left_buy_right_sell_spread >= right_buy_left_sell_spread
            latest_spread = max(left_buy_right_sell_spread, right_buy_left_sell_spread)
            absolute_price_diff = (
                abs(left_buy_right_sell_price_diff)
                if left_is_buy_leg
                else abs(right_buy_left_sell_price_diff)
            ) if has_market_data else 0.0
            buy_exchange_code = left_exchange_code if left_is_buy_leg else right_exchange_code
            sell_exchange_code = right_exchange_code if left_is_buy_leg else left_exchange_code
            buy_market_type = left_market_type if left_is_buy_leg else right_market_type
            sell_market_type = right_market_type if left_is_buy_leg else left_market_type
            buy_symbol_raw = str(pair["left_symbol"]) if left_is_buy_leg else str(pair["right_symbol"])
            sell_symbol_raw = str(pair["right_symbol"]) if left_is_buy_leg else str(pair["left_symbol"])
            buy_price_value = buy_price_value if left_is_buy_leg else reverse_buy_price_value
            sell_price_value = sell_price_value if left_is_buy_leg else reverse_sell_price_value
            left_mid_price_value = (
                ((float(left_ticker.bid_price) + float(left_ticker.ask_price)) / 2)
                if left_ticker is not None
                else 0.0
            )
            right_mid_price_value = (
                ((float(right_ticker.bid_price) + float(right_ticker.ask_price)) / 2)
                if right_ticker is not None
                else 0.0
            )
            cross_exchange_price_gap_percent = (
                self._calc_absolute_diff_percent(left_mid_price_value, right_mid_price_value)
                if has_market_data
                else 0.0
            )
            is_price_aligned = has_market_data and cross_exchange_price_gap_percent <= self._max_cross_exchange_price_gap_percent
            left_fee = self._resolve_fee_rate_value(market_type=left_market_type)
            right_fee = self._resolve_fee_rate_value(market_type=right_market_type)
            net_spread = latest_spread - left_fee - right_fee if has_market_data else 0.0
            left_funding = market_runtime_cache.get_funding_rate(left_exchange_code, str(pair["left_symbol"]))
            right_funding = market_runtime_cache.get_funding_rate(right_exchange_code, str(pair["right_symbol"]))
            has_funding_data = left_funding is not None and right_funding is not None
            funding_diff_percent = (
                abs(left_funding.funding_rate_percent - right_funding.funding_rate_percent)
                if has_funding_data
                else 0.0
            )

            result.append(
                {
                    "rank_sort": net_spread,
                    "market_pair_key": str(pair.get("pair_key") or ""),
                    "market_left_exchange_code": left_exchange_code,
                    "market_right_exchange_code": right_exchange_code,
                    "market_left_symbol_raw": str(pair["left_symbol"]),
                    "market_right_symbol_raw": str(pair["right_symbol"]),
                    "symbol": str(pair["base_asset"]),
                    "buy_exchange": self._exchange_label(buy_exchange_code),
                    "sell_exchange": self._exchange_label(sell_exchange_code),
                    "left_exchange_code": buy_exchange_code,
                    "right_exchange_code": sell_exchange_code,
                    "left_market_type": buy_market_type,
                    "right_market_type": sell_market_type,
                    "left_symbol_raw": buy_symbol_raw,
                    "right_symbol_raw": sell_symbol_raw,
                    "left_price_value": buy_price_value,
                    "right_price_value": sell_price_value,
                    "latest_spread": format_signed_percent(latest_spread, 2) if has_market_data else "--",
                    "latest_spread_value": latest_spread,
                    "left_buy_right_sell_spread_value": left_buy_right_sell_spread,
                    "right_buy_left_sell_spread_value": right_buy_left_sell_spread,
                    "net_spread": format_signed_percent(net_spread, 2) if has_market_data else "--",
                    "net_spread_value": net_spread,
                    "price_diff": self._format_price(absolute_price_diff) if has_market_data else "--",
                    "price_diff_value": absolute_price_diff,
                    "left_buy_right_sell_price_diff_value": left_buy_right_sell_price_diff,
                    "right_buy_left_sell_price_diff_value": right_buy_left_sell_price_diff,
                    "net_rate": format_signed_percent(funding_diff_percent, 4) if has_funding_data else "--",
                    "net_rate_value": funding_diff_percent,
                    "buy_funding_rate": (
                        format_signed_percent(
                            left_funding.funding_rate_percent if left_is_buy_leg and left_funding is not None else right_funding.funding_rate_percent,
                            4,
                        )
                        if has_funding_data and ((left_is_buy_leg and left_funding is not None) or right_funding is not None)
                        else "--"
                    ),
                    "sell_funding_rate": (
                        format_signed_percent(
                            right_funding.funding_rate_percent if left_is_buy_leg and right_funding is not None else left_funding.funding_rate_percent,
                            4,
                        )
                        if has_funding_data and ((left_is_buy_leg and right_funding is not None) or left_funding is not None)
                        else "--"
                    ),
                    "buy_fee_rate": self._resolve_fee_rate_display(market_type=buy_market_type),
                    "sell_fee_rate": self._resolve_fee_rate_display(market_type=sell_market_type),
                    "avg_long": self._format_price(buy_price_value),
                    "avg_short": self._format_price(sell_price_value),
                    "opportunity_time": self._format_datetime(left_ticker.synced_at or right_ticker.synced_at) if has_market_data and left_ticker is not None and right_ticker is not None else "--",
                    "has_market_data": has_market_data,
                    "is_market_data_fresh": is_market_data_fresh,
                    "is_market_data_display_ready": is_market_data_display_ready,
                    "is_price_aligned": is_price_aligned,
                    "cross_exchange_price_gap_percent_value": cross_exchange_price_gap_percent,
                }
            )

        return self._finalize_rows(result)

    def _finalize_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ordered = sorted(rows, key=lambda item: item["rank_sort"], reverse=True)
        for index, row in enumerate(ordered, start=1):
            row["rank"] = index
            row.pop("rank_sort", None)
        return ordered

    def _resolve_fee_rate_display(self, *, market_type: str) -> str:
        return f"{self._resolve_fee_rate_value(market_type=market_type):.2f}%"

    def _resolve_fee_rate_value(self, *, market_type: str) -> float:
        normalized_market_type = self._market_code_from_label(str(market_type or ""))
        if normalized_market_type == "spot":
            return 0.10
        return 0.05

    def _calc_price_gap_percent(self, sell_price: float, buy_price: float, *, absolute: bool = False) -> float:
        if sell_price <= 0 or buy_price <= 0:
            return 0.0
        percent = ((sell_price - buy_price) / buy_price) * 100
        return abs(percent) if absolute else percent

    def _calc_absolute_diff_percent(self, left_price: float, right_price: float) -> float:
        high_price = max(float(left_price or 0), float(right_price or 0))
        low_price = min(float(left_price or 0), float(right_price or 0))
        if high_price <= 0 or low_price <= 0:
            return 0.0
        return abs((high_price - low_price) / low_price) * 100

    def _filter_live_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in rows
            if bool(row.get("has_market_data"))
            and bool(row.get("is_market_data_display_ready", row.get("is_market_data_fresh")))
            and bool(row.get("is_price_aligned", True))
        ]

    def _prepare_display_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        prepared: List[Dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            next_row = dict(row)
            has_market_data = bool(next_row.get("has_market_data"))
            is_display_ready = bool(next_row.get("is_market_data_display_ready", next_row.get("is_market_data_fresh")))
            is_fresh = bool(next_row.get("is_market_data_fresh"))
            is_price_aligned = bool(next_row.get("is_price_aligned", True))
            is_tradable = has_market_data and is_display_ready and is_fresh and is_price_aligned

            if is_tradable:
                row_status = "live"
                row_status_message = "实时数据正常"
            elif has_market_data and not is_display_ready:
                row_status = "stale"
                row_status_message = "数据延迟，当前仅展示最近缓存"
            elif not has_market_data:
                row_status = "missing"
                row_status_message = "行情或资金费缺失，当前仅保留机会结构"
            else:
                row_status = "blocked"
                row_status_message = "跨交易所价格偏差过大，当前不可交易"

            next_row["row_status"] = row_status
            next_row["row_status_message"] = row_status_message
            next_row["tradable"] = is_tradable
            next_row["rank"] = int(next_row.get("rank") or index)
            prepared.append(next_row)

        return prepared

    def _is_market_data_fresh(
        self,
        *,
        left_ticker,
        right_ticker,
        left_funding,
        right_funding,
        stale_seconds: int | None = None,
    ) -> bool:
        timestamps: List[datetime] = []
        for candidate in (
            left_ticker.synced_at if left_ticker is not None else None,
            right_ticker.synced_at if right_ticker is not None else None,
            left_funding.synced_at if left_funding is not None else None,
            right_funding.synced_at if right_funding is not None else None,
        ):
            if isinstance(candidate, datetime):
                timestamps.append(candidate)
        if not timestamps:
            return False
        threshold_seconds = max(1, int(stale_seconds or self._market_data_execution_stale_seconds))
        threshold = datetime.now() - timedelta(seconds=threshold_seconds)
        return all(item >= threshold for item in timestamps)

    def _format_remaining(self, next_funding_at: datetime | None) -> str:
        if next_funding_at is None:
            return "--"
        seconds = int((next_funding_at - datetime.now()).total_seconds())
        return format_countdown(max(seconds, 0))

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
        normalized = str(label or "").strip().lower()
        if normalized in {"spot", "swap"}:
            return normalized
        return normalized

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
