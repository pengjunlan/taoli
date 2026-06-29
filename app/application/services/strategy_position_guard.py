"""Per-user position and capacity guards for strategy execution."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.application.services.funding_runtime_state_service import funding_runtime_state_service
from app.application.services.spread_runtime_state_service import spread_runtime_state_service
from app.application.services.strategy_risk_config import strategy_risk_config
from app.application.services.strategy_rule_runtime_service import StrategyRuleRuntimeView
from app.infrastructure.cache import redis_runtime_support
from app.infrastructure.persistence import arbitrage_execution_repository
from app.infrastructure.persistence.account_repository import account_repository


BUSY_OPEN_STATUSES = {"pending", "created", "processing", "opening", "closing"}
TERMINAL_BLOCK_STATUSES = set()


class StrategyPositionGuard:
    def evaluate_rule_pair_state(
        self,
        *,
        user_id: int,
        row: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
    ) -> tuple[str, bool]:
        pair_suffix = self.build_pair_suffix(row=row)
        if not pair_suffix:
            return "pair_key_missing", False

        pair_key = self.build_rule_pair_key(rule_id=runtime_rule.rule_id, row=row)
        if not pair_key:
            return "pair_key_missing", False

        latest_open = arbitrage_execution_repository.get_latest_active_open_execution_by_user_pair_suffix(
            user_id=user_id,
            pair_suffix=pair_suffix,
        )
        latest_status = str((latest_open or {}).get("status") or "").strip().lower()
        latest_pair_key = str((latest_open or {}).get("pair_key") or "").strip()
        latest_rule_id = int((latest_open or {}).get("strategy_rule_id") or 0)
        is_same_rule_pair = (
            latest_open is not None
            and latest_status == "open"
            and latest_rule_id == int(runtime_rule.rule_id or 0)
            and latest_pair_key == pair_key
        )

        if arbitrage_execution_repository.has_open_close_execution_by_user_pair_suffix(
            user_id=user_id,
            pair_suffix=pair_suffix,
        ):
            return "pair_has_closing_execution", is_same_rule_pair

        if self.is_pair_in_cooldown(user_id=user_id, pair_key=pair_key):
            return "pair_in_cooldown", is_same_rule_pair

        if latest_open is None:
            return "", False

        if latest_status == "open":
            if not is_same_rule_pair:
                return "pair_has_active_execution", False
            if not self.is_same_execution_direction(latest_open=latest_open, row=row):
                return "pair_direction_conflict", False
            add_block = self.evaluate_existing_pair_add_state(
                execution_row=latest_open,
                runtime_rule=runtime_rule,
            )
            return add_block, True

        if latest_status in BUSY_OPEN_STATUSES:
            return "pair_has_active_execution", False

        return "", False

    def evaluate_rule_state(
        self,
        *,
        row: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
        state: Dict[str, Any],
        pair_notional: Dict[str, float],
        account_available: Dict[int, float],
        is_existing_pair: bool = False,
    ) -> str:
        max_pairs = runtime_rule.max_pairs
        active_pair_count = int(state.get("active_pair_count") or 0)
        if max_pairs > 0 and not is_existing_pair and active_pair_count >= max_pairs:
            return "max_pairs_reached"
        if not self.has_order_capacity(
            row=row,
            order_amount=runtime_rule.order_amount_usdt,
            account_available=account_available,
        ):
            return "insufficient_available_balance"
        if self.would_exceed_max_position(
            row=row,
            rule_id=runtime_rule.rule_id,
            runtime_rule=runtime_rule,
            pair_notional=pair_notional,
        ):
            return "max_position_reached"
        return ""

    def build_rule_state(self, *, user_id: int, rule_rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        result: Dict[int, Dict[str, Any]] = {}
        for rule in rule_rows:
            rule_id = int(rule.get("id") or 0)
            if rule_id <= 0:
                continue
            result[rule_id] = {
                "active_pair_count": len(
                    arbitrage_execution_repository.list_active_open_pair_keys_by_rule(
                        user_id=user_id,
                        strategy_rule_id=rule_id,
                    )
                ),
            }
        return result

    def build_account_available_lookup(self, *, user_id: int) -> Dict[int, float]:
        result: Dict[int, float] = {}
        for row in account_repository.list_active_accounts_with_address_by_user_id(user_id):
            account_id = int(row.get("id") or 0)
            if account_id <= 0:
                continue
            result[account_id] = self._parse_float(row.get("current_available_amount"))
        return result

    def build_pair_notional_lookup(self, *, user_id: int, rule_rows: List[Dict[str, Any]]) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for rule in rule_rows:
            rule_id = int(rule.get("id") or 0)
            if rule_id <= 0:
                continue
            for pair_key in arbitrage_execution_repository.list_active_open_pair_keys_by_rule(
                user_id=user_id,
                strategy_rule_id=rule_id,
            ):
                executions = arbitrage_execution_repository.list_open_executions_by_rule_pair(
                    user_id=user_id,
                    strategy_rule_id=rule_id,
                    pair_key=str(pair_key),
                )
                position_notional = self.resolve_execution_pair_notional(executions[0] if executions else None)
                opening_notional = arbitrage_execution_repository.sum_opening_execution_planned_amount_without_position_by_pair(
                    user_id=user_id,
                    strategy_rule_id=rule_id,
                    pair_key=str(pair_key),
                )
                result[str(pair_key)] = position_notional + opening_notional
        return result

    def evaluate_existing_pair_add_state(
        self,
        *,
        execution_row: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
    ) -> str:
        if not self.is_pair_position_balanced(execution_row):
            return "pair_position_unbalanced"

        strategy_type = str(runtime_rule.strategy_type or "").strip().lower()
        interval_seconds = int(runtime_rule.order_interval_seconds or 0)
        if interval_seconds > 0:
            last_order_at = self._resolve_last_add_reference_time(execution_row=execution_row, runtime_rule=runtime_rule)
            if isinstance(last_order_at, datetime) and datetime.now() - last_order_at < timedelta(seconds=interval_seconds):
                return "order_interval_waiting"

        if strategy_type == "spread":
            spread_block = self._evaluate_spread_add_step(execution_row=execution_row, runtime_rule=runtime_rule)
            if spread_block:
                return spread_block
        return ""

    def is_pair_position_balanced(self, execution_row: Dict[str, Any]) -> bool:
        source_legs = arbitrage_execution_repository.list_order_legs_by_execution(
            execution_id=int(execution_row.get("id") or 0),
        )
        quantities: List[float] = []
        for leg in source_legs:
            quantity = arbitrage_execution_repository.get_position_quantity(
                exchange_account_id=int(leg.get("exchange_account_id") or 0),
                market_type=str(leg.get("market_type") or ""),
                symbol=str(leg.get("symbol") or ""),
                position_side=str(leg.get("position_side") or ""),
            )
            quantities.append(float(quantity or 0))

        if len(quantities) < 2:
            return False
        left_quantity, right_quantity = quantities[0], quantities[1]
        max_quantity = max(left_quantity, right_quantity)
        if max_quantity <= 0:
            return False
        tolerance = max(0.000001, max_quantity * max(0.0, strategy_risk_config.pair_balance_tolerance_ratio))
        return abs(left_quantity - right_quantity) <= tolerance

    def is_pair_in_cooldown(self, *, user_id: int, pair_key: str) -> bool:
        if user_id <= 0 or not pair_key:
            return False
        payload = redis_runtime_support.get_json(f"arbitrage:cooldown:user:{int(user_id)}:{pair_key}")
        if not isinstance(payload, dict):
            return False
        until_at = redis_runtime_support.parse_datetime(payload.get("until_at"))
        return bool(until_at and until_at > datetime.now())

    def would_exceed_max_position(
        self,
        *,
        row: Dict[str, Any],
        rule_id: int,
        runtime_rule: StrategyRuleRuntimeView,
        pair_notional: Dict[str, float],
    ) -> bool:
        if runtime_rule.max_position_usdt <= 0:
            return False
        pair_key = self.build_rule_pair_key(rule_id=rule_id, row=row)
        current_notional = pair_notional.get(pair_key, 0.0)
        return current_notional + runtime_rule.order_amount_usdt > runtime_rule.max_position_usdt

    def has_order_capacity(
        self,
        *,
        row: Dict[str, Any],
        order_amount: float,
        account_available: Dict[int, float],
    ) -> bool:
        if order_amount <= 0:
            return False
        left_account_id = int(row.get("left_account_id") or 0)
        right_account_id = int(row.get("right_account_id") or 0)
        if left_account_id <= 0 or right_account_id <= 0:
            return False
        return (
            account_available.get(left_account_id, 0.0) >= order_amount
            and account_available.get(right_account_id, 0.0) >= order_amount
        )

    def build_pair_suffix(self, *, row: Dict[str, Any]) -> str:
        market_pair_key = str(row.get("market_pair_key") or "").strip().lower()
        if market_pair_key:
            return market_pair_key

        left_exchange_code = str(row.get("left_exchange_code") or "").strip().lower()
        right_exchange_code = str(row.get("right_exchange_code") or "").strip().lower()
        ordered_codes = sorted(code for code in (left_exchange_code, right_exchange_code) if code)
        symbol = str(row.get("symbol") or "").strip()
        return f"{symbol}:{':'.join(ordered_codes)}"

    def build_rule_pair_key(self, *, rule_id: int, row: Dict[str, Any]) -> str:
        pair_suffix = self.build_pair_suffix(row=row)
        return f"{int(rule_id or 0)}:{pair_suffix}" if pair_suffix else ""

    def is_same_execution_direction(self, *, latest_open: Dict[str, Any], row: Dict[str, Any]) -> bool:
        latest_left_exchange = str(latest_open.get("left_exchange_code") or "").strip().lower()
        latest_right_exchange = str(latest_open.get("right_exchange_code") or "").strip().lower()
        latest_left_symbol = str(latest_open.get("left_symbol") or "").strip()
        latest_right_symbol = str(latest_open.get("right_symbol") or "").strip()

        row_left_exchange = str(row.get("left_exchange_code") or "").strip().lower()
        row_right_exchange = str(row.get("right_exchange_code") or "").strip().lower()
        row_left_symbol = str(row.get("left_symbol_raw") or row.get("left_symbol") or "").strip()
        row_right_symbol = str(row.get("right_symbol_raw") or row.get("right_symbol") or "").strip()

        if not latest_left_exchange or not latest_right_exchange or not row_left_exchange or not row_right_exchange:
            return True
        if not latest_left_symbol or not latest_right_symbol or not row_left_symbol or not row_right_symbol:
            return True
        return (
            latest_left_exchange == row_left_exchange
            and latest_right_exchange == row_right_exchange
            and latest_left_symbol == row_left_symbol
            and latest_right_symbol == row_right_symbol
        )

    def resolve_execution_pair_notional(self, execution: Dict[str, Any] | None) -> float:
        if execution is None:
            return 0.0
        user_id = int(execution.get("user_id") or 0)
        rule_id = int(execution.get("strategy_rule_id") or 0)
        pair_key = str(execution.get("pair_key") or "").strip()
        if user_id > 0 and rule_id > 0 and pair_key:
            positions = arbitrage_execution_repository.list_open_positions_by_pair(
                user_id=user_id,
                strategy_rule_id=rule_id,
                pair_key=pair_key,
            )
            if positions:
                notionals: List[float] = []
                for row in positions:
                    try:
                        quantity = abs(float(row.get("quantity") or 0))
                        market_value = abs(float(row.get("market_value_usdt") or 0))
                        mark_price = float(row.get("mark_price") or 0)
                        avg_price = float(row.get("avg_entry_price") or 0)
                    except (TypeError, ValueError):
                        continue
                    if market_value > 0:
                        notionals.append(market_value)
                        continue
                    price = mark_price if mark_price > 0 else avg_price
                    if quantity > 0 and price > 0:
                        notionals.append(quantity * price)
                if notionals:
                    return max(notionals)

        source_legs = arbitrage_execution_repository.list_order_legs_by_execution(
            execution_id=int(execution.get("id") or 0),
        )
        notionals: List[float] = []
        for leg in source_legs:
            notional = arbitrage_execution_repository.get_position_notional(
                exchange_account_id=int(leg.get("exchange_account_id") or 0),
                market_type=str(leg.get("market_type") or ""),
                symbol=str(leg.get("symbol") or ""),
                position_side=str(leg.get("position_side") or ""),
            )
            notionals.append(float(notional or 0))
        return max(notionals) if notionals else 0.0

    def _parse_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _resolve_last_add_reference_time(
        self,
        *,
        execution_row: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
    ) -> datetime | None:
        runtime_state = self._get_runtime_state(execution_row=execution_row, runtime_rule=runtime_rule)
        last_order_at = redis_runtime_support.parse_datetime(runtime_state.get("last_order_at"))
        if isinstance(last_order_at, datetime):
            return last_order_at
        updated_at = execution_row.get("updated_at")
        return updated_at if isinstance(updated_at, datetime) else None

    def _evaluate_spread_add_step(
        self,
        *,
        execution_row: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
    ) -> str:
        drawdown_step = float(runtime_rule.drawdown_add_step_percent or 0)
        if drawdown_step <= 0:
            return ""
        runtime_state = spread_runtime_state_service.get_pair_state(
            user_id=int(execution_row.get("user_id") or 0),
            rule_id=int(runtime_rule.rule_id or 0),
            pair_key=str(execution_row.get("pair_key") or ""),
        )
        last_spread_value = self._parse_float(runtime_state.get("last_open_spread_value"))
        latest_spread_value = self._parse_float(runtime_state.get("latest_spread_value"))
        if last_spread_value <= 0 or latest_spread_value <= 0:
            return ""
        if latest_spread_value < last_spread_value + drawdown_step:
            return "spread_add_step_not_reached"
        return ""

    def _get_runtime_state(
        self,
        *,
        execution_row: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
    ) -> Dict[str, Any]:
        user_id = int(execution_row.get("user_id") or 0)
        rule_id = int(runtime_rule.rule_id or 0)
        pair_key = str(execution_row.get("pair_key") or "")
        strategy_type = str(runtime_rule.strategy_type or "").strip().lower()
        if strategy_type == "funding":
            return funding_runtime_state_service.get_pair_state(
                user_id=user_id,
                rule_id=rule_id,
                pair_key=pair_key,
            )
        return spread_runtime_state_service.get_pair_state(
            user_id=user_id,
            rule_id=rule_id,
            pair_key=pair_key,
        )


strategy_position_guard = StrategyPositionGuard()


__all__ = [
    "BUSY_OPEN_STATUSES",
    "TERMINAL_BLOCK_STATUSES",
    "StrategyPositionGuard",
    "strategy_position_guard",
]
