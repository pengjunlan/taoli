"""Background worker for arbitrage close-condition monitoring."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.application.services.arbitrage_execution_plan_service import arbitrage_execution_plan_service
from app.application.services.arbitrage_runtime_support_service import arbitrage_runtime_support_service
from app.application.services.monitor_center_service import monitor_center_service
from app.application.services.opportunity_user_overlay_service import opportunity_user_overlay_service
from app.application.services.strategy_risk_config import strategy_risk_config
from app.application.services.strategy_open_candidate_service import strategy_open_candidate_service
from app.application.services.strategy_signal_evaluator import strategy_signal_evaluator
from app.application.services.strategy_rule_runtime_service import strategy_rule_runtime_service
from app.infrastructure.cache import market_runtime_cache
from app.infrastructure.persistence import arbitrage_execution_repository
from app.infrastructure.persistence.account_repository import account_repository


logger = logging.getLogger(__name__)


class ArbitragePositionMonitorService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._interval_seconds = strategy_risk_config.position_monitor_interval_seconds
        self._monitor_key = "arbitrage_position_monitor"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            monitor_center_service.register_worker(
                key=self._monitor_key,
                name="套利持仓监控线程",
                category="套利执行",
                thread_name="arbitrage-position-monitor",
                interval_seconds=self._interval_seconds,
                status="starting",
                detail="准备扫描开仓后的平仓条件",
            )
            self._thread = threading.Thread(
                target=self._run_loop,
                name="arbitrage-position-monitor",
                daemon=True,
            )
            self._thread.start()

    def _run_loop(self) -> None:
        while True:
            try:
                created_count = self._scan_open_executions()
                monitor_center_service.mark_success(
                    self._monitor_key,
                    f"本轮平仓条件扫描完成，新增平仓执行 {created_count} 条",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Arbitrage position monitor loop failed: %s", exc)
                monitor_center_service.mark_error(self._monitor_key, f"套利持仓监控异常: {exc}")
            time.sleep(self._interval_seconds)

    def _scan_open_executions(self) -> int:
        rows = arbitrage_execution_repository.list_active_open_executions(limit=300)
        created_count = 0
        processed_pair_keys: set[tuple[int, int, str]] = set()
        for execution_row in rows:
            status = str(execution_row.get("status") or "").strip().lower()
            if status not in {"opening", "open", "closing"}:
                continue

            pair_identity = (
                int(execution_row.get("user_id") or 0),
                int(execution_row.get("strategy_rule_id") or 0),
                str(execution_row.get("pair_key") or "").strip(),
            )
            if pair_identity[0] > 0 and pair_identity[1] > 0 and pair_identity[2]:
                if pair_identity in processed_pair_keys:
                    continue
                processed_pair_keys.add(pair_identity)

            latest_close = arbitrage_execution_repository.get_latest_active_close_execution_by_pair(
                user_id=int(execution_row.get("user_id") or 0),
                strategy_rule_id=int(execution_row.get("strategy_rule_id") or 0),
                pair_key=str(execution_row.get("pair_key") or ""),
            )
            latest_close_status = str((latest_close or {}).get("status") or "").strip().lower()
            if latest_close is not None and latest_close_status in {"pending", "created", "processing", "opening", "open", "closing"}:
                if status != "closing":
                    arbitrage_execution_repository.update_execution_status(
                        execution_id=int(execution_row.get("id") or 0),
                        status="closing",
                    )
                continue

            position_state = self._inspect_execution_positions(execution_row=execution_row)
            if not position_state["has_live_position"]:
                if status == "opening":
                    continue
                self._close_pair_open_execution_statuses(execution_row=execution_row)
                monitor_center_service.add_log(
                    self._monitor_key,
                    "info",
                    f"执行 #{execution_row.get('id')} 已无剩余持仓，自动标记为已平仓",
                )
                continue

            if position_state["is_unhedged"]:
                result = arbitrage_execution_plan_service.create_close_execution(
                    execution_row=execution_row,
                    reason="[stop_loss] 检测到单腿持仓或对冲失衡，继续执行强制平仓",
                    close_amount_usdt=float("inf"),
                )
                if result is None:
                    continue
                created_count += 1
                arbitrage_execution_repository.update_execution_status(
                    execution_id=int(execution_row.get("id") or 0),
                    status="closing",
                )
                monitor_center_service.add_log(
                    self._monitor_key,
                    "warning",
                    f"执行 #{execution_row.get('id')} 检测到单腿暴露，新增强制平仓执行 #{result.execution_id}",
                )
                continue

            strategy_rule = account_repository.get_strategy_rule_by_id(
                int(execution_row.get("strategy_rule_id") or 0),
                int(execution_row.get("user_id") or 0),
            )
            if strategy_rule is None:
                continue

            reason = self._resolve_close_reason(execution_row=execution_row, strategy_rule=strategy_rule)
            if not reason:
                continue

            close_amount_usdt = self._resolve_close_amount_usdt(
                execution_row=execution_row,
                strategy_rule=strategy_rule,
                reason=reason,
            )
            if close_amount_usdt <= 0:
                continue

            result = arbitrage_execution_plan_service.create_close_execution(
                execution_row=execution_row,
                reason=reason,
                close_amount_usdt=close_amount_usdt,
            )
            if result is None:
                continue
            created_count += 1
            arbitrage_execution_repository.update_execution_status(
                execution_id=int(execution_row.get("id") or 0),
                status="closing",
            )
            monitor_center_service.add_log(
                self._monitor_key,
                "info",
                f"执行 #{execution_row.get('id')} 触发平仓，新增平仓执行 #{result.execution_id}",
            )
        return created_count

    def _inspect_execution_positions(self, *, execution_row: Dict[str, Any]) -> Dict[str, bool]:
        source_legs = arbitrage_execution_repository.list_order_legs_by_execution(
            execution_id=int(execution_row.get("id") or 0),
        )
        left_source_leg = next((row for row in source_legs if str(row.get("leg_role") or "") == "left"), None)
        right_source_leg = next((row for row in source_legs if str(row.get("leg_role") or "") == "right"), None)
        if left_source_leg is None or right_source_leg is None:
            return {
                "has_live_position": False,
                "is_unhedged": False,
                "is_balanced": False,
            }

        left_quantity = self._resolve_position_quantity(
            exchange_account_id=int(left_source_leg.get("exchange_account_id") or 0),
            market_type=str(execution_row.get("left_market_type") or ""),
            symbol=str(execution_row.get("left_symbol") or ""),
            position_side=str(left_source_leg.get("position_side") or "long"),
        )
        right_quantity = self._resolve_position_quantity(
            exchange_account_id=int(right_source_leg.get("exchange_account_id") or 0),
            market_type=str(execution_row.get("right_market_type") or ""),
            symbol=str(execution_row.get("right_symbol") or ""),
            position_side=str(right_source_leg.get("position_side") or "short"),
        )

        left_has = left_quantity > 0
        right_has = right_quantity > 0
        max_quantity = max(left_quantity, right_quantity)
        tolerance = max(0.000001, max_quantity * strategy_risk_config.pair_balance_tolerance_ratio) if max_quantity > 0 else 0.0
        return {
            "has_live_position": left_has or right_has,
            "is_unhedged": left_has != right_has,
            "is_balanced": left_has and right_has and abs(left_quantity - right_quantity) <= tolerance,
        }

    def _resolve_position_quantity(
        self,
        *,
        exchange_account_id: int,
        market_type: str,
        symbol: str,
        position_side: str,
    ) -> float:
        quantity = arbitrage_execution_repository.get_position_quantity(
            exchange_account_id=exchange_account_id,
            market_type=market_type,
            symbol=symbol,
            position_side=position_side,
        )
        return float(quantity or 0)

    def _resolve_close_reason(
        self,
        *,
        execution_row: Dict[str, Any],
        strategy_rule: Dict[str, Any],
    ) -> str:
        strategy_type = str(execution_row.get("strategy_type") or "").strip().lower()
        opportunity = self._find_runtime_opportunity(execution_row=execution_row)
        runtime_rule = strategy_rule_runtime_service.build_runtime_view(strategy_rule)

        if opportunity is None:
            timed_reason = self._resolve_timed_close_reason(
                execution_row=execution_row,
                strategy_rule=strategy_rule,
            )
            if timed_reason:
                return timed_reason
            opportunity = self._build_fallback_opportunity(execution_row=execution_row)
            if opportunity is None:
                return ""
        elif not strategy_open_candidate_service.is_display_status_eligible(opportunity):
            timed_reason = self._resolve_timed_close_reason(
                execution_row=execution_row,
                strategy_rule=strategy_rule,
            )
            if timed_reason:
                return timed_reason
            fallback_opportunity = self._build_fallback_opportunity(execution_row=execution_row)
            if fallback_opportunity is None:
                return ""
            opportunity = fallback_opportunity

        close_reason = strategy_signal_evaluator.evaluate_close_reason(
            strategy_type=strategy_type,
            execution_row=execution_row,
            opportunity=opportunity,
            rule=strategy_rule,
            runtime_rule=runtime_rule,
        )
        if close_reason:
            return close_reason

        timed_reason = self._resolve_timed_close_reason(
            execution_row=execution_row,
            strategy_rule=strategy_rule,
        )
        if timed_reason:
            return timed_reason

        return close_reason

    def _find_runtime_opportunity(self, *, execution_row: Dict[str, Any]) -> Dict[str, Any] | None:
        user_id = int(execution_row.get("user_id") or 0)
        channel = str(execution_row.get("strategy_type") or "").strip().lower()
        state = market_runtime_cache.get_public_rows_state(channel)
        rows: List[Dict[str, Any]] = list(state.rows) if state is not None else []
        rows = opportunity_user_overlay_service.enrich_execution_rows(
            user_id=user_id,
            channel=channel,
            rows=rows,
        )
        pair_key = str(execution_row.get("pair_key") or "")
        for row in rows:
            market_pair_key = str(row.get("market_pair_key") or "").strip().lower()
            if pair_key.endswith(market_pair_key) and market_pair_key:
                return row
        return None

    def _build_fallback_opportunity(self, *, execution_row: Dict[str, Any]) -> Dict[str, Any] | None:
        strategy_type = str(execution_row.get("strategy_type") or "").strip().lower()
        left_symbol = str(execution_row.get("left_symbol") or "").strip()
        right_symbol = str(execution_row.get("right_symbol") or "").strip()
        left_exchange_code = str(execution_row.get("left_exchange_code") or "").strip().lower()
        right_exchange_code = str(execution_row.get("right_exchange_code") or "").strip().lower()
        left_market_type = str(execution_row.get("left_market_type") or "").strip().lower()
        right_market_type = str(execution_row.get("right_market_type") or "").strip().lower()
        if not left_symbol or not right_symbol or not left_exchange_code or not right_exchange_code:
            return None

        left_buy_price = arbitrage_runtime_support_service.get_latest_price(
            exchange_code=left_exchange_code,
            market_type=left_market_type,
            symbol=left_symbol,
            side="buy",
            prefer_post_only=True,
        )
        left_sell_price = arbitrage_runtime_support_service.get_latest_price(
            exchange_code=left_exchange_code,
            market_type=left_market_type,
            symbol=left_symbol,
            side="sell",
            prefer_post_only=True,
        )
        right_buy_price = arbitrage_runtime_support_service.get_latest_price(
            exchange_code=right_exchange_code,
            market_type=right_market_type,
            symbol=right_symbol,
            side="buy",
            prefer_post_only=True,
        )
        right_sell_price = arbitrage_runtime_support_service.get_latest_price(
            exchange_code=right_exchange_code,
            market_type=right_market_type,
            symbol=right_symbol,
            side="sell",
            prefer_post_only=True,
        )
        if min(left_buy_price, left_sell_price, right_buy_price, right_sell_price) <= 0:
            return None

        left_buy_right_sell_spread = ((right_sell_price - left_buy_price) / left_buy_price) * 100 if left_buy_price > 0 else 0.0
        right_buy_left_sell_spread = ((left_sell_price - right_buy_price) / right_buy_price) * 100 if right_buy_price > 0 else 0.0
        cross_gap = ((max(left_sell_price, right_sell_price) - min(left_buy_price, right_buy_price)) / min(left_buy_price, right_buy_price) * 100)

        opportunity = {
            "market_pair_key": self._pair_suffix_from_execution(execution_row),
            "symbol": str(execution_row.get("base_asset") or "").replace("USDT", "") or str(execution_row.get("symbol") or "").replace("USDT", ""),
            "market_left_exchange_code": left_exchange_code,
            "market_right_exchange_code": right_exchange_code,
            "left_exchange_code": left_exchange_code,
            "right_exchange_code": right_exchange_code,
            "left_symbol_raw": left_symbol,
            "right_symbol_raw": right_symbol,
            "left_price_value": left_buy_price,
            "right_price_value": right_sell_price,
            "left_buy_right_sell_spread_value": left_buy_right_sell_spread,
            "right_buy_left_sell_spread_value": right_buy_left_sell_spread,
            "latest_spread_value": (
                left_buy_right_sell_spread
                if str(execution_row.get("left_exchange_code") or "").strip().lower() == left_exchange_code
                else right_buy_left_sell_spread
            ),
            "latest_spread": f"{left_buy_right_sell_spread:.4f}%",
            "net_spread_value": (
                left_buy_right_sell_spread
                if str(execution_row.get("left_exchange_code") or "").strip().lower() == left_exchange_code
                else right_buy_left_sell_spread
            ),
            "net_spread": f"{left_buy_right_sell_spread:.4f}%",
            "price_diff_value": abs(cross_gap),
            "price_diff": f"{abs(cross_gap):.4f}%",
            "cross_exchange_price_gap_percent_value": abs(cross_gap),
            "has_market_data": True,
            "is_market_data_fresh": True,
            "is_price_aligned": True,
            "execution_ready": True,
            "tradable": True,
            "row_status": "live",
            "status_code": 1,
        }
        if strategy_type == "funding":
            left_funding = market_runtime_cache.get_funding_rate(left_exchange_code, left_symbol)
            right_funding = market_runtime_cache.get_funding_rate(right_exchange_code, right_symbol)
            left_funding_rate_4h = self._normalize_funding_rate_percent(left_funding)
            right_funding_rate_4h = self._normalize_funding_rate_percent(right_funding)
            left_long_right_short = right_funding_rate_4h - left_funding_rate_4h
            right_long_left_short = left_funding_rate_4h - right_funding_rate_4h
            long_settlement_at = left_funding.next_funding_at if left_funding is not None else None
            short_settlement_at = right_funding.next_funding_at if right_funding is not None else None
            next_funding_at = self._resolve_earliest_datetime(long_settlement_at, short_settlement_at)
            opportunity.update(
                {
                    "market_left_exchange_code": left_exchange_code,
                    "market_right_exchange_code": right_exchange_code,
                    "left_long_right_short_net_rate_value": left_long_right_short,
                    "right_long_left_short_net_rate_value": right_long_left_short,
                    "net_rate_value": abs(left_long_right_short),
                    "net_rate": f"{abs(left_long_right_short):.4f}%",
                    "spread_value": self._funding_signed_spread_percent(
                        long_price=left_buy_price,
                        short_price=right_sell_price,
                    ),
                    "spread": f"{self._funding_signed_spread_percent(long_price=left_buy_price, short_price=right_sell_price):.4f}%",
                    "settlement_at_ms": self._to_epoch_milliseconds(next_funding_at),
                    "long_settlement_at_ms": self._to_epoch_milliseconds(long_settlement_at),
                    "short_settlement_at_ms": self._to_epoch_milliseconds(short_settlement_at),
                }
            )
        return opportunity

    def _resolve_earliest_datetime(self, *values: datetime | None) -> datetime | None:
        candidates = [value for value in values if isinstance(value, datetime)]
        if not candidates:
            return None
        return min(candidates, key=lambda item: item.timestamp())

    def _to_epoch_milliseconds(self, value: datetime | None) -> int | None:
        if value is None:
            return None
        return int(value.timestamp() * 1000)

    def _normalize_funding_rate_percent(self, funding_item: Any) -> float:
        if funding_item is None:
            return 0.0
        try:
            rate = float(getattr(funding_item, "funding_rate_percent", 0) or 0)
            interval_hours = float(getattr(funding_item, "settlement_interval_hours", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        if interval_hours <= 0:
            interval_hours = 8.0
        return rate / max(interval_hours, 1e-9) * 4.0

    def _funding_signed_spread_percent(self, *, long_price: float, short_price: float) -> float:
        if long_price <= 0 or short_price <= 0:
            return 0.0
        return ((short_price - long_price) / long_price) * 100

    def _pair_suffix_from_execution(self, execution_row: Dict[str, Any]) -> str:
        pair_key = str(execution_row.get("pair_key") or "").strip()
        if ":" not in pair_key:
            return pair_key
        return pair_key.split(":", 1)[1]

    def _resolve_timed_close_reason(
        self,
        *,
        execution_row: Dict[str, Any],
        strategy_rule: Dict[str, Any],
    ) -> str:
        max_hold_minutes = max(0, int(strategy_rule.get("max_hold_minutes") or 0))
        if max_hold_minutes <= 0:
            return ""
        created_at = execution_row.get("created_at")
        if not isinstance(created_at, datetime):
            return ""
        held_seconds = (datetime.now() - created_at).total_seconds()
        if held_seconds < max_hold_minutes * 60:
            return ""
        return f"持仓已超过最大持有时间 {max_hold_minutes} 分钟，触发正常平仓"

    def _resolve_close_amount_usdt(
        self,
        *,
        execution_row: Dict[str, Any],
        strategy_rule: Dict[str, Any],
        reason: str,
    ) -> float:
        if self._is_fast_risk_close(reason):
            return float("inf")

        close_interval_seconds = max(0, int(strategy_rule.get("close_interval_seconds") or 0))
        if close_interval_seconds > 0:
            latest_close = arbitrage_execution_repository.get_latest_close_execution_by_pair(
                user_id=int(execution_row.get("user_id") or 0),
                strategy_rule_id=int(execution_row.get("strategy_rule_id") or 0),
                pair_key=str(execution_row.get("pair_key") or ""),
            )
            if latest_close is not None:
                updated_at = latest_close.get("updated_at")
                if isinstance(updated_at, datetime) and datetime.now() - updated_at < timedelta(seconds=close_interval_seconds):
                    return 0.0

        close_batch_amount_usdt = self._parse_float(strategy_rule.get("close_batch_ratio_percent"))
        if close_batch_amount_usdt <= 0:
            return float("inf")
        close_batch_count = max(0, int(strategy_rule.get("close_batch_count") or 0))
        if close_batch_count > 0:
            closed_count = arbitrage_execution_repository.count_closed_close_executions_by_source(
                source_execution_id=int(execution_row.get("id") or 0),
            )
            if closed_count >= max(0, close_batch_count - 1):
                return float("inf")
        return close_batch_amount_usdt

    def _close_pair_open_execution_statuses(self, *, execution_row: Dict[str, Any]) -> None:
        user_id = int(execution_row.get("user_id") or 0)
        rule_id = int(execution_row.get("strategy_rule_id") or 0)
        pair_key = str(execution_row.get("pair_key") or "").strip()
        if user_id <= 0 or rule_id <= 0 or not pair_key:
            execution_id = int(execution_row.get("id") or 0)
            if execution_id > 0:
                arbitrage_execution_repository.update_execution_status(
                    execution_id=execution_id,
                    status="closed",
                )
            return

        pair_open_executions = arbitrage_execution_repository.list_open_executions_by_rule_pair(
            user_id=user_id,
            strategy_rule_id=rule_id,
            pair_key=pair_key,
        )
        for row in pair_open_executions:
            execution_id = int(row.get("id") or 0)
            if execution_id <= 0:
                continue
            current_status = str(row.get("status") or "").strip().lower()
            if current_status == "closed":
                continue
            arbitrage_execution_repository.update_execution_status(
                execution_id=execution_id,
                status="closed",
            )

    def _is_fast_risk_close(self, reason: str) -> bool:
        normalized = str(reason or "").lower()
        return any(
            keyword in normalized
            for keyword in (
                "止损",
                "单腿",
                "暴露",
                "超过最大价差",
                "最大资金费成本",
                "强制",
                "stop_loss",
                "force_close",
                "risk_close",
                "[stop_loss]",
                "unhedged",
                "exposure",
            )
        )

    def _parse_percent(self, value: Any) -> float:
        text = str(value or "").replace("%", "").replace("+", "").replace(",", "").strip()
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _parse_float(self, value: Any, *, fallback: Any = 0) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return self._parse_percent(fallback)


arbitrage_position_monitor_service = ArbitragePositionMonitorService()
