"""Create arbitrage execution records from live opportunities and strategy rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.application.services.arbitrage_runtime_support_service import arbitrage_runtime_support_service
from app.infrastructure.persistence import arbitrage_execution_repository


@dataclass(frozen=True)
class ExecutionPlanResult:
    execution_id: int
    created_order_leg_ids: List[int]


class ArbitrageExecutionPlanService:
    def create_open_execution(
        self,
        *,
        user_id: int,
        strategy_rule: Dict[str, Any],
        opportunity: Dict[str, Any],
    ) -> Optional[ExecutionPlanResult]:
        strategy_type = str(strategy_rule.get("strategy_type") or "").strip().lower()
        if strategy_type == "funding":
            return self._create_funding_open_execution(
                user_id=user_id,
                strategy_rule=strategy_rule,
                opportunity=opportunity,
            )
        if strategy_type == "spread":
            return self._create_spread_open_execution(
                user_id=user_id,
                strategy_rule=strategy_rule,
                opportunity=opportunity,
            )
        return None

    def create_close_execution(
        self,
        *,
        execution_row: Dict[str, Any],
        reason: str,
    ) -> Optional[ExecutionPlanResult]:
        if str(execution_row.get("action") or "open") == "close":
            return None

        source_legs = arbitrage_execution_repository.list_order_legs_by_execution(
            execution_id=int(execution_row.get("id") or 0),
        )
        left_source_leg = next((row for row in source_legs if str(row.get("leg_role") or "") == "left"), None)
        right_source_leg = next((row for row in source_legs if str(row.get("leg_role") or "") == "right"), None)
        if left_source_leg is None or right_source_leg is None:
            return None

        left_side, right_side = self._close_sides_by_strategy_type(str(execution_row.get("strategy_type") or ""))
        left_position_side = str(left_source_leg.get("position_side") or "long")
        right_position_side = str(right_source_leg.get("position_side") or "short")
        left_position = arbitrage_execution_repository.get_open_position(
            exchange_account_id=int(left_source_leg.get("exchange_account_id") or 0),
            market_type=str(execution_row.get("left_market_type") or ""),
            symbol=str(execution_row.get("left_symbol") or ""),
            position_side=left_position_side,
        )
        right_position = arbitrage_execution_repository.get_open_position(
            exchange_account_id=int(right_source_leg.get("exchange_account_id") or 0),
            market_type=str(execution_row.get("right_market_type") or ""),
            symbol=str(execution_row.get("right_symbol") or ""),
            position_side=right_position_side,
        )
        left_base_quantity = float((left_position or {}).get("quantity") or 0)
        right_base_quantity = float((right_position or {}).get("quantity") or 0)
        if left_base_quantity <= 0 and right_base_quantity <= 0:
            return None
        left_plan = None
        if left_base_quantity > 0:
            left_plan = arbitrage_runtime_support_service.build_quantity_plan(
                exchange_code=str(execution_row.get("left_exchange_code") or ""),
                market_type=str(execution_row.get("left_market_type") or ""),
                symbol=str(execution_row.get("left_symbol") or ""),
                side=left_side,
                order_amount_usdt=0,
                base_quantity=left_base_quantity,
            )
            if left_plan.order_quantity <= 0:
                left_plan = None

        right_plan = None
        if right_base_quantity > 0:
            right_plan = arbitrage_runtime_support_service.build_quantity_plan(
                exchange_code=str(execution_row.get("right_exchange_code") or ""),
                market_type=str(execution_row.get("right_market_type") or ""),
                symbol=str(execution_row.get("right_symbol") or ""),
                side=right_side,
                order_amount_usdt=0,
                base_quantity=right_base_quantity,
            )
            if right_plan.order_quantity <= 0:
                right_plan = None

        if left_plan is None and right_plan is None:
            return None
        planned_close_amount = sum(
            float(plan.order_value_usdt or 0)
            for plan in (left_plan, right_plan)
            if plan is not None
        )

        execution_id = arbitrage_execution_repository.create_execution(
            user_id=int(execution_row.get("user_id") or 0),
            strategy_type=str(execution_row.get("strategy_type") or ""),
            source_execution_id=int(execution_row.get("id") or 0) or None,
            pair_key=str(execution_row.get("pair_key") or ""),
            action="close",
            symbol=str(execution_row.get("symbol") or ""),
            base_asset=str(execution_row.get("base_asset") or ""),
            quote_asset=str(execution_row.get("quote_asset") or "USDT"),
            left_exchange_code=str(execution_row.get("left_exchange_code") or ""),
            right_exchange_code=str(execution_row.get("right_exchange_code") or ""),
            left_market_type=str(execution_row.get("left_market_type") or ""),
            right_market_type=str(execution_row.get("right_market_type") or ""),
            left_symbol=str(execution_row.get("left_symbol") or ""),
            right_symbol=str(execution_row.get("right_symbol") or ""),
            planned_order_amount_usdt=planned_close_amount,
            max_position_usdt=float(execution_row.get("max_position_usdt") or 0),
            trigger_metric_primary="close",
            trigger_metric_secondary="close",
            trigger_metric_risk="close",
            trigger_reason=reason,
            strategy_rule_id=int(execution_row.get("strategy_rule_id") or 0),
            strategy_rule_name=str(execution_row.get("strategy_rule_name") or ""),
            status="pending",
        )

        created_order_leg_ids: List[int] = []
        if left_plan is not None:
            created_order_leg_ids.append(
                arbitrage_execution_repository.create_order_leg(
                    execution_id=execution_id,
                    user_id=int(execution_row.get("user_id") or 0),
                    exchange_account_id=int(left_source_leg.get("exchange_account_id") or 0) or None,
                    leg_role="left",
                    position_side=left_position_side,
                    exchange_code=str(execution_row.get("left_exchange_code") or ""),
                    market_type=str(execution_row.get("left_market_type") or ""),
                    symbol=str(execution_row.get("left_symbol") or ""),
                    side=left_side,
                    order_type="limit",
                    requested_price=left_plan.requested_price,
                    requested_quantity=left_plan.order_quantity,
                    requested_value_usdt=left_plan.order_value_usdt,
                    status="pending",
                    status_message=reason,
                )
            )
        if right_plan is not None:
            created_order_leg_ids.append(
                arbitrage_execution_repository.create_order_leg(
                    execution_id=execution_id,
                    user_id=int(execution_row.get("user_id") or 0),
                    exchange_account_id=int(right_source_leg.get("exchange_account_id") or 0) or None,
                    leg_role="right",
                    position_side=right_position_side,
                    exchange_code=str(execution_row.get("right_exchange_code") or ""),
                    market_type=str(execution_row.get("right_market_type") or ""),
                    symbol=str(execution_row.get("right_symbol") or ""),
                    side=right_side,
                    order_type="limit",
                    requested_price=right_plan.requested_price,
                    requested_quantity=right_plan.order_quantity,
                    requested_value_usdt=right_plan.order_value_usdt,
                    status="pending",
                    status_message=reason,
                )
            )

        return ExecutionPlanResult(
            execution_id=execution_id,
            created_order_leg_ids=created_order_leg_ids,
        )

    def _create_funding_open_execution(
        self,
        *,
        user_id: int,
        strategy_rule: Dict[str, Any],
        opportunity: Dict[str, Any],
    ) -> Optional[ExecutionPlanResult]:
        left_account_id = int(opportunity.get("left_account_id") or 0)
        right_account_id = int(opportunity.get("right_account_id") or 0)
        if left_account_id <= 0 or right_account_id <= 0:
            return None

        order_amount = float(strategy_rule.get("order_amount_usdt") or 0)
        left_position_side = "long"
        left_side = "buy"
        right_position_side = "short"
        right_side = "sell"
        left_plan = arbitrage_runtime_support_service.build_quantity_plan(
            exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            market_type="swap",
            symbol=str(opportunity.get("left_symbol_raw") or ""),
            side=left_side,
            order_amount_usdt=order_amount,
        )
        right_plan = arbitrage_runtime_support_service.build_quantity_plan(
            exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
            market_type="swap",
            symbol=str(opportunity.get("right_symbol_raw") or ""),
            side=right_side,
            order_amount_usdt=order_amount,
            base_quantity=left_plan.base_quantity,
        )
        if left_plan.order_quantity <= 0 or right_plan.order_quantity <= 0:
            return None

        pair_key = self._build_pair_key(
            strategy_rule_id=int(strategy_rule.get("id") or 0),
            market_pair_key=str(opportunity.get("market_pair_key") or ""),
            symbol=str(opportunity.get("symbol") or ""),
            left_exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            right_exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
        )
        execution_id = arbitrage_execution_repository.create_execution(
            user_id=user_id,
            strategy_type="funding",
            source_execution_id=None,
            pair_key=pair_key,
            action="open",
            symbol=f"{str(opportunity.get('symbol') or '')}USDT",
            base_asset=str(opportunity.get("symbol") or ""),
            quote_asset="USDT",
            left_exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            right_exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
            left_market_type="swap",
            right_market_type="swap",
            left_symbol=str(opportunity.get("left_symbol_raw") or ""),
            right_symbol=str(opportunity.get("right_symbol_raw") or ""),
            planned_order_amount_usdt=order_amount,
            max_position_usdt=float(strategy_rule.get("max_position_usdt") or order_amount),
            trigger_metric_primary=str(opportunity.get("net_rate") or ""),
            trigger_metric_secondary=str(opportunity.get("annual") or ""),
            trigger_metric_risk=str(opportunity.get("spread") or ""),
            trigger_reason=(
                f"资金费开仓: 净资金费率 {opportunity.get('net_rate') or '--'} / "
                f"年化 {opportunity.get('annual') or '--'} / "
                f"价差 {opportunity.get('spread') or '--'}"
            ),
            strategy_rule_id=int(strategy_rule.get("id") or 0),
            strategy_rule_name=str(strategy_rule.get("name") or ""),
            status="pending",
        )

        left_leg_id = arbitrage_execution_repository.create_order_leg(
            execution_id=execution_id,
            user_id=user_id,
            exchange_account_id=left_account_id,
            leg_role="left",
            position_side=left_position_side,
            exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            market_type="swap",
            symbol=str(opportunity.get("left_symbol_raw") or ""),
            side=left_side,
            order_type="limit",
            requested_price=left_plan.requested_price,
            requested_quantity=left_plan.order_quantity,
            requested_value_usdt=left_plan.order_value_usdt,
            status="pending",
            status_message="资金费开仓左腿待提交",
        )
        right_leg_id = arbitrage_execution_repository.create_order_leg(
            execution_id=execution_id,
            user_id=user_id,
            exchange_account_id=right_account_id,
            leg_role="right",
            position_side=right_position_side,
            exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
            market_type="swap",
            symbol=str(opportunity.get("right_symbol_raw") or ""),
            side=right_side,
            order_type="limit",
            requested_price=right_plan.requested_price,
            requested_quantity=right_plan.order_quantity,
            requested_value_usdt=right_plan.order_value_usdt,
            status="pending",
            status_message="资金费开仓右腿待提交",
        )

        return ExecutionPlanResult(
            execution_id=execution_id,
            created_order_leg_ids=[left_leg_id, right_leg_id],
        )

    def _create_spread_open_execution(
        self,
        *,
        user_id: int,
        strategy_rule: Dict[str, Any],
        opportunity: Dict[str, Any],
    ) -> Optional[ExecutionPlanResult]:
        left_account_id = int(opportunity.get("left_account_id") or 0)
        right_account_id = int(opportunity.get("right_account_id") or 0)
        if left_account_id <= 0 or right_account_id <= 0:
            return None

        order_amount = float(strategy_rule.get("order_amount_usdt") or 0)
        left_market_type = str(opportunity.get("left_market_type") or "swap")
        right_market_type = str(opportunity.get("right_market_type") or "swap")
        if left_market_type != "swap" or right_market_type != "swap":
            return None
        left_position_side = "long"
        left_side = "buy"
        right_position_side = "short"
        right_side = "sell"
        left_plan = arbitrage_runtime_support_service.build_quantity_plan(
            exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            market_type=left_market_type,
            symbol=str(opportunity.get("left_symbol_raw") or ""),
            side=left_side,
            order_amount_usdt=order_amount,
        )
        right_plan = arbitrage_runtime_support_service.build_quantity_plan(
            exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
            market_type=right_market_type,
            symbol=str(opportunity.get("right_symbol_raw") or ""),
            side=right_side,
            order_amount_usdt=order_amount,
            base_quantity=left_plan.base_quantity,
        )
        if left_plan.order_quantity <= 0 or right_plan.order_quantity <= 0:
            return None

        pair_key = self._build_pair_key(
            strategy_rule_id=int(strategy_rule.get("id") or 0),
            market_pair_key=str(opportunity.get("market_pair_key") or ""),
            symbol=str(opportunity.get("symbol") or ""),
            left_exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            right_exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
        )
        execution_id = arbitrage_execution_repository.create_execution(
            user_id=user_id,
            strategy_type="spread",
            source_execution_id=None,
            pair_key=pair_key,
            action="open",
            symbol=f"{str(opportunity.get('symbol') or '')}USDT",
            base_asset=str(opportunity.get("symbol") or ""),
            quote_asset="USDT",
            left_exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            right_exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
            left_market_type=left_market_type,
            right_market_type=right_market_type,
            left_symbol=str(opportunity.get("left_symbol_raw") or ""),
            right_symbol=str(opportunity.get("right_symbol_raw") or ""),
            planned_order_amount_usdt=order_amount,
            max_position_usdt=float(strategy_rule.get("max_position_usdt") or order_amount),
            trigger_metric_primary=str(opportunity.get("latest_spread") or ""),
            trigger_metric_secondary=str(opportunity.get("net_spread") or ""),
            trigger_metric_risk=(
                f"{opportunity.get('buy_fee_rate') or '--'} / {opportunity.get('sell_fee_rate') or '--'}"
            ),
            trigger_reason=(
                f"价差开仓: 最新价差 {opportunity.get('latest_spread') or '--'} / "
                f"净价差 {opportunity.get('net_spread') or '--'}"
            ),
            strategy_rule_id=int(strategy_rule.get("id") or 0),
            strategy_rule_name=str(strategy_rule.get("name") or ""),
            status="pending",
        )

        left_leg_id = arbitrage_execution_repository.create_order_leg(
            execution_id=execution_id,
            user_id=user_id,
            exchange_account_id=left_account_id,
            leg_role="left",
            position_side=left_position_side,
            exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            market_type=left_market_type,
            symbol=str(opportunity.get("left_symbol_raw") or ""),
            side=left_side,
            order_type="limit",
            requested_price=left_plan.requested_price,
            requested_quantity=left_plan.order_quantity,
            requested_value_usdt=left_plan.order_value_usdt,
            status="pending",
            status_message="价差开仓左腿待提交",
        )
        right_leg_id = arbitrage_execution_repository.create_order_leg(
            execution_id=execution_id,
            user_id=user_id,
            exchange_account_id=right_account_id,
            leg_role="right",
            position_side=right_position_side,
            exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
            market_type=right_market_type,
            symbol=str(opportunity.get("right_symbol_raw") or ""),
            side=right_side,
            order_type="limit",
            requested_price=right_plan.requested_price,
            requested_quantity=right_plan.order_quantity,
            requested_value_usdt=right_plan.order_value_usdt,
            status="pending",
            status_message="价差开仓右腿待提交",
        )

        return ExecutionPlanResult(
            execution_id=execution_id,
            created_order_leg_ids=[left_leg_id, right_leg_id],
        )

    def _build_pair_key(
        self,
        *,
        strategy_rule_id: int,
        market_pair_key: str,
        symbol: str,
        left_exchange_code: str,
        right_exchange_code: str,
    ) -> str:
        normalized_market_pair_key = str(market_pair_key or "").strip().lower()
        if normalized_market_pair_key:
            return f"{strategy_rule_id}:{normalized_market_pair_key}"

        ordered_codes = sorted(
            code.strip().lower()
            for code in (left_exchange_code, right_exchange_code)
            if str(code or "").strip()
        )
        return f"{strategy_rule_id}:{symbol}:{':'.join(ordered_codes)}"

    def _close_sides_by_strategy_type(self, strategy_type: str) -> tuple[str, str]:
        _ = strategy_type
        return ("sell", "buy")


arbitrage_execution_plan_service = ArbitrageExecutionPlanService()
