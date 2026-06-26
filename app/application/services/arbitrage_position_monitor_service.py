"""Background worker for arbitrage close-condition monitoring."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.application.services.arbitrage_execution_plan_service import arbitrage_execution_plan_service
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
        for execution_row in rows:
            status = str(execution_row.get("status") or "")
            if status not in {"open", "closing"}:
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
                    reason="[stop_loss] 检测到单腿持仓或对冲失衡，继续执行强制平仓",
                    close_fraction=1.0,
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

            close_fraction = self._resolve_close_fraction(
                execution_row=execution_row,
                strategy_rule=strategy_rule,
                reason=reason,
            )
            if close_fraction <= 0:
                continue

            result = arbitrage_execution_plan_service.create_close_execution(
                execution_row=execution_row,
                reason=reason,
                close_fraction=close_fraction,
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

        if opportunity is None or not strategy_open_candidate_service.is_trading_status_normal(opportunity):
            return ""

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

    def _resolve_close_fraction(
        self,
        *,
        execution_row: Dict[str, Any],
        strategy_rule: Dict[str, Any],
        reason: str,
    ) -> float:
        if self._is_fast_risk_close(reason):
            return 1.0

        close_interval_seconds = max(0, int(strategy_rule.get("close_interval_seconds") or 0))
        if close_interval_seconds > 0:
            latest_close = arbitrage_execution_repository.get_latest_close_execution_by_source(
                source_execution_id=int(execution_row.get("id") or 0),
            )
            if latest_close is not None:
                updated_at = latest_close.get("updated_at")
                if isinstance(updated_at, datetime) and datetime.now() - updated_at < timedelta(seconds=close_interval_seconds):
                    return 0.0

        close_batch_count = max(0, int(strategy_rule.get("close_batch_count") or 0))
        close_batch_ratio_percent = self._parse_float(strategy_rule.get("close_batch_ratio_percent"))
        if close_batch_ratio_percent > 0:
            return min(1.0, max(0.0, close_batch_ratio_percent / 100.0))

        if close_batch_count <= 1:
            return 1.0
        closed_batches = arbitrage_execution_repository.count_closed_close_executions_by_source(
            source_execution_id=int(execution_row.get("id") or 0),
        )
        remaining_batches = max(1, close_batch_count - int(closed_batches or 0))
        return min(1.0, max(0.0, 1.0 / remaining_batches))

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
