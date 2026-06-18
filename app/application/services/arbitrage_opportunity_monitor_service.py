"""Monitor opportunities and create arbitrage execution records."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.application.services.arbitrage_execution_plan_service import arbitrage_execution_plan_service
from app.application.services.monitor_center_service import monitor_center_service
from app.application.services.strategy_rule_runtime_service import strategy_rule_runtime_service
from app.infrastructure.cache import redis_runtime_support
from app.infrastructure.persistence import arbitrage_execution_repository
from app.infrastructure.persistence.account_repository import account_repository


logger = logging.getLogger(__name__)


class ArbitrageOpportunityMonitorService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._interval_seconds = 5
        self._monitor_key = "arbitrage_opportunity_monitor"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            monitor_center_service.register_worker(
                key=self._monitor_key,
                name="套利机会监控线程",
                category="套利执行",
                thread_name="arbitrage-opportunity-monitor",
                interval_seconds=self._interval_seconds,
                status="starting",
                detail="准备扫描机会并生成套利执行记录",
            )
            self._thread = threading.Thread(
                target=self._run_loop,
                name="arbitrage-opportunity-monitor",
                daemon=True,
            )
            self._thread.start()

    def _run_loop(self) -> None:
        while True:
            try:
                created_count = self._scan_all_users()
                monitor_center_service.mark_success(
                    self._monitor_key,
                    f"本轮扫描完成，新增套利执行 {created_count} 条",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Arbitrage opportunity monitor failed: %s", exc)
                monitor_center_service.mark_error(self._monitor_key, f"套利机会监控异常: {exc}")
            time.sleep(self._interval_seconds)

    def _scan_all_users(self) -> int:
        rows = account_repository.list_all_accounts_with_address()
        user_ids = sorted({int(row["user_id"]) for row in rows})
        created_count = 0
        for user_id in user_ids:
            created_count += self._scan_user(user_id)
        return created_count

    def _scan_user(self, user_id: int) -> int:
        strategy_rows = [row for row in account_repository.list_strategy_rules_by_user_id(user_id) if bool(row.get("is_enabled"))]
        if not strategy_rows:
            return 0

        funding_rows = self._load_opportunity_rows(channel="funding", user_id=user_id)
        spread_rows = self._load_opportunity_rows(channel="spread", user_id=user_id)
        created_count = 0

        for strategy_rule in strategy_rows:
            strategy_type = str(strategy_rule.get("strategy_type") or "").strip().lower()
            if strategy_type == "funding":
                created_count += self._scan_strategy_opportunities(user_id, strategy_rule, funding_rows)
            elif strategy_type == "spread":
                created_count += self._scan_strategy_opportunities(user_id, strategy_rule, spread_rows)

        return created_count

    def _scan_strategy_opportunities(
        self,
        user_id: int,
        strategy_rule: Dict[str, Any],
        opportunity_rows: List[Dict[str, Any]],
    ) -> int:
        runtime_rule = strategy_rule_runtime_service.build_runtime_view(strategy_rule)
        max_pairs = runtime_rule.max_pairs
        max_position = runtime_rule.max_position_quantity
        active_pair_keys = set(
            arbitrage_execution_repository.list_active_open_pair_keys_by_rule(
                user_id=user_id,
                strategy_rule_id=int(strategy_rule.get("id") or 0),
            )
        )
        current_open_pairs = len(active_pair_keys)

        created_count = 0
        for opportunity in opportunity_rows:
            if not self._should_open(strategy_rule, opportunity):
                continue

            pair_key = self._build_pair_key(strategy_rule, opportunity)
            is_existing_pair = pair_key in active_pair_keys
            if max_pairs > 0 and not is_existing_pair and current_open_pairs >= max_pairs:
                continue
            if self._is_in_cooldown(user_id=user_id, pair_key=pair_key):
                continue
            if not self._can_continue_after_interval(user_id=user_id, strategy_rule=strategy_rule, pair_key=pair_key):
                continue

            if max_position > 0 and self._resolve_pair_leg_quantity(user_id=user_id, strategy_rule=strategy_rule, pair_key=pair_key) >= max_position:
                continue

            result = arbitrage_execution_plan_service.create_open_execution(
                user_id=user_id,
                strategy_rule=strategy_rule,
                opportunity=opportunity,
            )
            if result is None:
                continue

            if not is_existing_pair:
                active_pair_keys.add(pair_key)
                current_open_pairs = len(active_pair_keys)
            created_count += 1
            monitor_center_service.add_log(
                self._monitor_key,
                "info",
                f"用户 {user_id} 策略 {strategy_rule.get('name') or '--'} 已生成执行 #{result.execution_id}",
            )

            if max_pairs > 0 and current_open_pairs >= max_pairs:
                break

        return created_count

    def _should_open(self, strategy_rule: Dict[str, Any], opportunity: Dict[str, Any]) -> bool:
        if not bool(opportunity.get("execution_ready")):
            return False
        runtime_rule = strategy_rule_runtime_service.build_runtime_view(strategy_rule)
        max_spread = runtime_rule.stop_loss_price_diff
        if runtime_rule.strategy_type == "funding":
            net_rate = self._parse_float(opportunity.get("net_rate_value"), fallback=opportunity.get("net_rate"))
            price_diff = self._parse_float(opportunity.get("price_diff_value"), fallback=opportunity.get("price_diff"))
            if net_rate <= runtime_rule.open_threshold:
                return False
            if max_spread > 0 and price_diff > max_spread:
                return False
            return True

        if runtime_rule.strategy_type == "spread":
            latest_spread = self._parse_float(opportunity.get("latest_spread_value"), fallback=opportunity.get("latest_spread"))
            price_diff = self._parse_float(opportunity.get("price_diff_value"), fallback=opportunity.get("price_diff"))
            if latest_spread < runtime_rule.open_threshold:
                return False
            if max_spread > 0 and price_diff > max_spread:
                return False
            return True

        return False

    def _build_pair_key(self, strategy_rule: Dict[str, Any], opportunity: Dict[str, Any]) -> str:
        market_pair_key = str(opportunity.get("market_pair_key") or "").strip().lower()
        if market_pair_key:
            return f"{int(strategy_rule.get('id') or 0)}:{market_pair_key}"

        left_exchange_code = str(opportunity.get("left_exchange_code") or "").strip().lower()
        right_exchange_code = str(opportunity.get("right_exchange_code") or "").strip().lower()
        ordered_codes = sorted(code for code in [left_exchange_code, right_exchange_code] if code)
        return f"{int(strategy_rule.get('id') or 0)}:{opportunity.get('symbol') or ''}:{':'.join(ordered_codes)}"

    def _can_continue_after_interval(
        self,
        *,
        user_id: int,
        strategy_rule: Dict[str, Any],
        pair_key: str,
    ) -> bool:
        latest_open = arbitrage_execution_repository.get_latest_open_execution_by_pair(
            user_id=user_id,
            strategy_rule_id=int(strategy_rule.get("id") or 0),
            pair_key=pair_key,
        )
        if latest_open is None:
            return True

        latest_status = str(latest_open.get("status") or "")
        if latest_status != "open":
            return True

        if not self._is_pair_position_balanced(latest_open):
            return False

        order_interval_seconds = strategy_rule_runtime_service.build_runtime_view(strategy_rule).order_interval_seconds
        if order_interval_seconds <= 0:
            return True

        updated_at = latest_open.get("updated_at")
        if not isinstance(updated_at, datetime):
            return True

        return datetime.now() - updated_at >= timedelta(seconds=order_interval_seconds)

    def _load_opportunity_rows(self, *, channel: str, user_id: int) -> List[Dict[str, Any]]:
        payload = redis_runtime_support.get_json(f"opportunity:{channel}:user:{int(user_id)}")
        if not isinstance(payload, dict):
            return []
        return list(payload.get("rows") or [])

    def _cooldown_key(self, *, user_id: int, pair_key: str) -> str:
        return f"arbitrage:cooldown:user:{int(user_id)}:{pair_key}"

    def _is_in_cooldown(self, *, user_id: int, pair_key: str) -> bool:
        payload = redis_runtime_support.get_json(self._cooldown_key(user_id=user_id, pair_key=pair_key))
        if not isinstance(payload, dict):
            return False
        until_at = redis_runtime_support.parse_datetime(payload.get("until_at"))
        return bool(until_at and until_at > datetime.now())

    def mark_pair_cooldown(self, *, user_id: int, pair_key: str, seconds: int = 3600) -> None:
        until_at = datetime.now() + timedelta(seconds=max(1, int(seconds or 3600)))
        redis_runtime_support.set_json(
            self._cooldown_key(user_id=user_id, pair_key=pair_key),
            {"until_at": until_at},
            ttl_seconds=max(1, int(seconds or 3600)),
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

    def _resolve_pair_leg_quantity(
        self,
        *,
        user_id: int,
        strategy_rule: Dict[str, Any],
        pair_key: str,
    ) -> float:
        latest_open = arbitrage_execution_repository.get_latest_open_execution_by_pair(
            user_id=user_id,
            strategy_rule_id=int(strategy_rule.get("id") or 0),
            pair_key=pair_key,
        )
        if latest_open is None:
            return 0.0
        quantities = self._pair_leg_quantities(latest_open)
        return max(quantities["left_quantity"], quantities["right_quantity"])

    def _is_pair_position_balanced(self, execution_row: Dict[str, Any]) -> bool:
        quantities = self._pair_leg_quantities(execution_row)
        left_quantity = quantities["left_quantity"]
        right_quantity = quantities["right_quantity"]
        max_quantity = max(left_quantity, right_quantity)
        if max_quantity <= 0:
            return False
        tolerance = max(0.000001, max_quantity * 0.02)
        return abs(left_quantity - right_quantity) <= tolerance

    def _pair_leg_quantities(self, execution_row: Dict[str, Any]) -> Dict[str, float]:
        source_legs = arbitrage_execution_repository.list_order_legs_by_execution(
            execution_id=int(execution_row.get("id") or 0),
        )
        left_source_leg = next((row for row in source_legs if str(row.get("leg_role") or "") == "left"), None)
        right_source_leg = next((row for row in source_legs if str(row.get("leg_role") or "") == "right"), None)
        if left_source_leg is None or right_source_leg is None:
            return {"left_quantity": 0.0, "right_quantity": 0.0}

        left_quantity = float(
            arbitrage_execution_repository.get_position_quantity(
                exchange_account_id=int(left_source_leg.get("exchange_account_id") or 0),
                market_type=str(execution_row.get("left_market_type") or ""),
                symbol=str(execution_row.get("left_symbol") or ""),
                position_side=str(left_source_leg.get("position_side") or "long"),
            ) or 0
        )
        right_quantity = float(
            arbitrage_execution_repository.get_position_quantity(
                exchange_account_id=int(right_source_leg.get("exchange_account_id") or 0),
                market_type=str(execution_row.get("right_market_type") or ""),
                symbol=str(execution_row.get("right_symbol") or ""),
                position_side=str(right_source_leg.get("position_side") or "short"),
            ) or 0
        )
        return {
            "left_quantity": left_quantity,
            "right_quantity": right_quantity,
        }


arbitrage_opportunity_monitor_service = ArbitrageOpportunityMonitorService()
