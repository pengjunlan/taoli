"""Background worker for arbitrage close-condition monitoring."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List

from app.application.services.arbitrage_execution_plan_service import arbitrage_execution_plan_service
from app.application.services.monitor_center_service import monitor_center_service
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
        self._interval_seconds = 5
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
                monitor_center_service.mark_error(
                    self._monitor_key,
                    f"套利持仓监控异常: {exc}",
                )
            time.sleep(self._interval_seconds)

    def _scan_open_executions(self) -> int:
        rows = arbitrage_execution_repository.list_active_open_executions(limit=300)
        created_count = 0
        for execution_row in rows:
            status = str(execution_row.get("status") or "")
            if status != "open":
                continue

            if arbitrage_execution_repository.has_open_close_execution(
                user_id=int(execution_row.get("user_id") or 0),
                strategy_rule_id=int(execution_row.get("strategy_rule_id") or 0),
                pair_key=str(execution_row.get("pair_key") or ""),
            ):
                continue

            position_state = self._inspect_execution_positions(execution_row=execution_row)
            if not position_state["has_live_position"]:
                arbitrage_execution_repository.update_execution_status(
                    execution_id=int(execution_row.get("id") or 0),
                    status="closed",
                )
                monitor_center_service.add_log(
                    self._monitor_key,
                    "info",
                    f"执行 #{execution_row.get('id')} 已无剩余持仓，自动标记为已平仓",
                )
                continue

            if position_state["is_unhedged"]:
                result = arbitrage_execution_plan_service.create_close_execution(
                    execution_row=execution_row,
                    reason="检测到单腿持仓或对冲失衡，继续执行强制平仓",
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

            if arbitrage_execution_repository.has_open_close_execution(
                user_id=int(execution_row.get("user_id") or 0),
                strategy_rule_id=int(execution_row.get("strategy_rule_id") or 0),
                pair_key=str(execution_row.get("pair_key") or ""),
            ):
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
            result = arbitrage_execution_plan_service.create_close_execution(
                execution_row=execution_row,
                reason=reason,
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
        tolerance = max(0.000001, max_quantity * 0.02) if max_quantity > 0 else 0.0
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
        if opportunity is None:
            return ""

        runtime_rule = strategy_rule_runtime_service.build_runtime_view(strategy_rule)
        max_spread = runtime_rule.stop_loss_price_diff
        if strategy_type == "funding":
            net_rate = self._resolve_funding_close_metric(execution_row=execution_row, opportunity=opportunity)
            price_diff = self._parse_float(opportunity.get("price_diff_value"), fallback=opportunity.get("price_diff"))
            if net_rate < runtime_rule.close_threshold:
                return (
                    f"净资金费率回落到 {opportunity.get('net_rate') or '--'}，"
                    f"低于最小净资金费率 {runtime_rule.close_threshold:.4f}%，触发平仓"
                )
            if max_spread > 0 and price_diff > max_spread:
                return f"价格差达到 {opportunity.get('price_diff') or '--'}，超过最大价差，触发平仓"
            return ""

        if strategy_type == "spread":
            latest_spread = self._resolve_spread_close_metric(execution_row=execution_row, opportunity=opportunity)
            price_diff = self._parse_float(opportunity.get("price_diff_value"), fallback=opportunity.get("price_diff"))
            if latest_spread <= runtime_rule.close_threshold:
                return f"价差回落到 {opportunity.get('latest_spread') or '--'}，触发平仓"
            if max_spread > 0 and price_diff > max_spread:
                return f"价格差达到 {opportunity.get('price_diff') or '--'}，超过最大价差，触发止损平仓"
            return ""

        return ""

    def _find_runtime_opportunity(self, *, execution_row: Dict[str, Any]) -> Dict[str, Any] | None:
        user_id = int(execution_row.get("user_id") or 0)
        channel = str(execution_row.get("strategy_type") or "").strip().lower()
        state = market_runtime_cache.get_user_rows_state(channel, user_id)
        rows: List[Dict[str, Any]] = list(state.rows) if state is not None else []
        pair_key = str(execution_row.get("pair_key") or "")
        for row in rows:
            market_pair_key = str(row.get("market_pair_key") or "").strip().lower()
            if pair_key.endswith(market_pair_key) and market_pair_key:
                return row
        return None

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

    def _resolve_funding_close_metric(self, *, execution_row: Dict[str, Any], opportunity: Dict[str, Any]) -> float:
        left_exchange = str(execution_row.get("left_exchange_code") or "").strip().lower()
        right_exchange = str(execution_row.get("right_exchange_code") or "").strip().lower()
        market_left_exchange = str(opportunity.get("market_left_exchange_code") or "").strip().lower()
        market_right_exchange = str(opportunity.get("market_right_exchange_code") or "").strip().lower()
        left_long_right_short = self._parse_float(
            opportunity.get("left_long_right_short_net_rate_value"),
            fallback=opportunity.get("net_rate"),
        )
        right_long_left_short = self._parse_float(
            opportunity.get("right_long_left_short_net_rate_value"),
            fallback=opportunity.get("net_rate"),
        )
        if left_exchange == market_left_exchange and right_exchange == market_right_exchange:
            return left_long_right_short
        if left_exchange == market_right_exchange and right_exchange == market_left_exchange:
            return right_long_left_short
        return self._parse_float(opportunity.get("net_rate_value"), fallback=opportunity.get("net_rate"))

    def _resolve_spread_close_metric(self, *, execution_row: Dict[str, Any], opportunity: Dict[str, Any]) -> float:
        left_exchange = str(execution_row.get("left_exchange_code") or "").strip().lower()
        right_exchange = str(execution_row.get("right_exchange_code") or "").strip().lower()
        market_left_exchange = str(opportunity.get("market_left_exchange_code") or "").strip().lower()
        market_right_exchange = str(opportunity.get("market_right_exchange_code") or "").strip().lower()
        left_buy_right_sell = self._parse_float(
            opportunity.get("left_buy_right_sell_spread_value"),
            fallback=opportunity.get("latest_spread"),
        )
        right_buy_left_sell = self._parse_float(
            opportunity.get("right_buy_left_sell_spread_value"),
            fallback=opportunity.get("latest_spread"),
        )
        if left_exchange == market_left_exchange and right_exchange == market_right_exchange:
            return left_buy_right_sell
        if left_exchange == market_right_exchange and right_exchange == market_left_exchange:
            return right_buy_left_sell
        return self._parse_float(opportunity.get("latest_spread_value"), fallback=opportunity.get("latest_spread"))


arbitrage_position_monitor_service = ArbitragePositionMonitorService()
