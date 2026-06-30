"""Create arbitrage execution records from live opportunities and strategy rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.application.services.arbitrage_runtime_support_service import arbitrage_runtime_support_service
from app.application.services.funding_runtime_state_service import funding_runtime_state_service
from app.application.services.opportunity_user_overlay_service import opportunity_user_overlay_service
from app.application.services.spread_runtime_state_service import spread_runtime_state_service
from app.application.services.strategy_open_candidate_service import strategy_open_candidate_service
from app.infrastructure.persistence import arbitrage_execution_repository
from app.infrastructure.persistence.account_repository import account_repository


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
        strategy_rule = self._resolve_current_enabled_rule(user_id=user_id, strategy_rule=strategy_rule)
        if strategy_rule is None:
            return None
        strategy_type = str(strategy_rule.get("strategy_type") or "").strip().lower()
        opportunity = self._prepare_execution_opportunity(
            user_id=user_id,
            strategy_type=strategy_type,
            opportunity=opportunity,
        )
        if not bool(opportunity.get("execution_ready")) or not self._is_trading_status_normal(opportunity):
            return None
        if not self._is_open_candidate(
            user_id=user_id,
            strategy_type=strategy_type,
            strategy_rule=strategy_rule,
            opportunity=opportunity,
        ):
            return None

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
        close_amount_usdt: float = 0.0,
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
        original_left_base_quantity = left_base_quantity
        original_right_base_quantity = right_base_quantity
        if left_base_quantity <= 0 and right_base_quantity <= 0:
            return None
        requested_close_amount = max(0.0, float(close_amount_usdt or 0))
        left_market_value = float((left_position or {}).get("market_value_usdt") or 0)
        if left_market_value <= 0:
            left_mark_price = float((left_position or {}).get("mark_price") or 0)
            left_avg_price = float((left_position or {}).get("avg_entry_price") or 0)
            left_price = left_mark_price if left_mark_price > 0 else left_avg_price
            left_market_value = left_base_quantity * left_price if left_price > 0 else 0.0
        right_market_value = float((right_position or {}).get("market_value_usdt") or 0)
        if right_market_value <= 0:
            right_mark_price = float((right_position or {}).get("mark_price") or 0)
            right_avg_price = float((right_position or {}).get("avg_entry_price") or 0)
            right_price = right_mark_price if right_mark_price > 0 else right_avg_price
            right_market_value = right_base_quantity * right_price if right_price > 0 else 0.0
        left_has_live_position = left_base_quantity > 0
        right_has_live_position = right_base_quantity > 0
        both_legs_live = left_has_live_position and right_has_live_position
        if requested_close_amount > 0:
            pair_market_value = max(left_market_value, right_market_value)
            close_ratio = min(1.0, requested_close_amount / pair_market_value) if pair_market_value > 0 else 0.0
            if close_ratio > 0:
                if left_market_value > 0:
                    left_base_quantity *= close_ratio
                if right_market_value > 0:
                    right_base_quantity *= close_ratio
        if left_base_quantity <= 0 and right_base_quantity <= 0:
            return None
        pair_plan = None
        if left_base_quantity > 0 and right_base_quantity > 0:
            pair_plan = arbitrage_runtime_support_service.build_pair_quantity_plan(
                left_exchange_code=str(execution_row.get("left_exchange_code") or ""),
                left_market_type=str(execution_row.get("left_market_type") or ""),
                left_symbol=str(execution_row.get("left_symbol") or ""),
                left_side=left_side,
                right_exchange_code=str(execution_row.get("right_exchange_code") or ""),
                right_market_type=str(execution_row.get("right_market_type") or ""),
                right_symbol=str(execution_row.get("right_symbol") or ""),
                right_side=right_side,
                base_quantity=min(left_base_quantity, right_base_quantity),
            )
        left_plan = pair_plan.left_plan if pair_plan is not None else None
        right_plan = pair_plan.right_plan if pair_plan is not None else None

        if pair_plan is None and left_base_quantity > 0 and right_base_quantity <= 0:
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

        if pair_plan is None and right_base_quantity > 0 and left_base_quantity <= 0:
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

        if both_legs_live and requested_close_amount > 0 and (left_plan is None or right_plan is None):
            pair_plan = arbitrage_runtime_support_service.build_pair_quantity_plan(
                left_exchange_code=str(execution_row.get("left_exchange_code") or ""),
                left_market_type=str(execution_row.get("left_market_type") or ""),
                left_symbol=str(execution_row.get("left_symbol") or ""),
                left_side=left_side,
                right_exchange_code=str(execution_row.get("right_exchange_code") or ""),
                right_market_type=str(execution_row.get("right_market_type") or ""),
                right_symbol=str(execution_row.get("right_symbol") or ""),
                right_side=right_side,
                base_quantity=min(original_left_base_quantity, original_right_base_quantity),
            )
            left_plan = pair_plan.left_plan if pair_plan is not None else None
            right_plan = pair_plan.right_plan if pair_plan is not None else None

        if both_legs_live and (left_plan is None or right_plan is None):
            return None
        if left_plan is None and right_plan is None:
            return None
        planned_close_amount = sum(
            float(plan.order_value_usdt or 0)
            for plan in (left_plan, right_plan)
            if plan is not None
        )
        if planned_close_amount <= 0:
            return None

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

        target_order_amount = float(strategy_rule.get("order_amount_usdt") or 0)
        split_order_amount = float(strategy_rule.get("split_order_amount_usdt") or 0)
        order_amount = split_order_amount if split_order_amount > 0 else target_order_amount
        left_position_side = "long"
        left_side = "buy"
        right_position_side = "short"
        right_side = "sell"
        pair_plan = arbitrage_runtime_support_service.build_pair_quantity_plan(
            left_exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            left_market_type="swap",
            left_symbol=str(opportunity.get("left_symbol_raw") or ""),
            left_side=left_side,
            right_exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
            right_market_type="swap",
            right_symbol=str(opportunity.get("right_symbol_raw") or ""),
            right_side=right_side,
            order_amount_usdt=order_amount,
        )
        if pair_plan is None:
            return None
        left_plan = pair_plan.left_plan
        right_plan = pair_plan.right_plan

        pair_key = self._build_pair_key(
            strategy_rule_id=int(strategy_rule.get("id") or 0),
            market_pair_key=str(opportunity.get("market_pair_key") or ""),
            symbol=str(opportunity.get("symbol") or ""),
            left_exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            right_exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
        )
        settlement_marker = self._build_funding_settlement_marker(opportunity)
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
            planned_order_amount_usdt=target_order_amount,
            max_position_usdt=float(strategy_rule.get("max_position_usdt") or target_order_amount),
            trigger_metric_primary=str(opportunity.get("net_rate") or ""),
            trigger_metric_secondary=f"{opportunity.get('annual') or ''}{settlement_marker}",
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

        funding_runtime_state_service.patch_pair_state(
            user_id=user_id,
            rule_id=int(strategy_rule.get("id") or 0),
            pair_key=pair_key,
            target_order_amount_usdt=target_order_amount,
            split_order_amount_usdt=order_amount,
            latest_net_rate_value=float(opportunity.get("net_rate_value") or 0),
            last_open_net_rate_value=float(opportunity.get("net_rate_value") or 0),
            latest_spread_value=float(opportunity.get("spread_value") or 0),
            last_open_spread_value=float(opportunity.get("spread_value") or 0),
            last_order_at=None,
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

        target_order_amount = float(strategy_rule.get("order_amount_usdt") or 0)
        split_order_amount = float(strategy_rule.get("split_order_amount_usdt") or 0)
        order_amount = split_order_amount if split_order_amount > 0 else target_order_amount
        left_market_type = str(opportunity.get("left_market_type") or "swap")
        right_market_type = str(opportunity.get("right_market_type") or "swap")
        if left_market_type != "swap" or right_market_type != "swap":
            return None
        left_position_side = "long"
        left_side = "buy"
        right_position_side = "short"
        right_side = "sell"
        pair_plan = arbitrage_runtime_support_service.build_pair_quantity_plan(
            left_exchange_code=str(opportunity.get("left_exchange_code") or "").lower(),
            left_market_type=left_market_type,
            left_symbol=str(opportunity.get("left_symbol_raw") or ""),
            left_side=left_side,
            right_exchange_code=str(opportunity.get("right_exchange_code") or "").lower(),
            right_market_type=right_market_type,
            right_symbol=str(opportunity.get("right_symbol_raw") or ""),
            right_side=right_side,
            order_amount_usdt=order_amount,
        )
        if pair_plan is None:
            return None
        left_plan = pair_plan.left_plan
        right_plan = pair_plan.right_plan

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
            planned_order_amount_usdt=target_order_amount,
            max_position_usdt=float(strategy_rule.get("max_position_usdt") or target_order_amount),
            trigger_metric_primary=str(opportunity.get("latest_spread") or ""),
            trigger_metric_secondary=str(opportunity.get("net_spread") or ""),
            trigger_metric_risk=str(opportunity.get("price_diff") or ""),
            trigger_reason=(
                f"价差开仓: 最新价差 {opportunity.get('latest_spread') or '--'} / "
                f"净价差 {opportunity.get('net_spread') or '--'} / "
                f"目标 {target_order_amount:.2f}U / 子委托 {order_amount:.2f}U"
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

        spread_runtime_state_service.patch_pair_state(
            user_id=user_id,
            rule_id=int(strategy_rule.get("id") or 0),
            pair_key=pair_key,
            target_order_amount_usdt=target_order_amount,
            split_order_amount_usdt=order_amount,
            latest_spread_value=float(opportunity.get("latest_spread_value") or 0),
            latest_net_spread_value=float(opportunity.get("net_spread_value") or 0),
            last_open_spread_value=float(opportunity.get("latest_spread_value") or 0),
            last_open_net_spread_value=float(opportunity.get("net_spread_value") or 0),
            last_order_at=None,
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

    def _resolve_current_enabled_rule(
        self,
        *,
        user_id: int,
        strategy_rule: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        rule_id = int(strategy_rule.get("id") or 0)
        if user_id <= 0 or rule_id <= 0:
            return None
        current_rule = account_repository.get_strategy_rule_by_id(rule_id, user_id)
        if current_rule is None or not bool(current_rule.get("is_enabled")):
            return None
        return current_rule

    def _prepare_execution_opportunity(
        self,
        *,
        user_id: int,
        strategy_type: str,
        opportunity: Dict[str, Any],
    ) -> Dict[str, Any]:
        rows = opportunity_user_overlay_service.enrich_execution_rows(
            user_id=user_id,
            channel=strategy_type,
            rows=[opportunity],
        )
        return rows[0] if rows else dict(opportunity)

    def _is_open_candidate(
        self,
        *,
        user_id: int,
        strategy_type: str,
        strategy_rule: Dict[str, Any],
        opportunity: Dict[str, Any],
    ) -> bool:
        context = strategy_open_candidate_service.build_evaluation_context(
            user_id=user_id,
            channel=strategy_type,
            rule_rows=[strategy_rule],
        )
        result = strategy_open_candidate_service.evaluate_execution_rule(
            user_id=user_id,
            channel=strategy_type,
            row=opportunity,
            rule=strategy_rule,
            context=context,
        )
        return bool(result.is_candidate)

    def _is_trading_status_normal(self, row: Dict[str, Any]) -> bool:
        status_code = row.get("status_code")
        if status_code not in (None, ""):
            try:
                if int(status_code) != 1:
                    return False
            except (TypeError, ValueError):
                return False
        row_status = str(row.get("row_status") or "").strip().lower()
        if row_status and row_status != "live":
            return False
        if "tradable" in row and not bool(row.get("tradable")):
            return False
        if bool(row.get("is_frozen")):
            return False
        if not bool(row.get("has_market_data")):
            return False
        if not bool(row.get("is_market_data_fresh")):
            return False
        if not bool(row.get("is_price_aligned", True)):
            return False
        return True

    def _build_funding_settlement_marker(self, opportunity: Dict[str, Any]) -> str:
        values: List[int] = []
        for field_name in ("long_settlement_at_ms", "short_settlement_at_ms", "settlement_at_ms"):
            try:
                value = int(float(opportunity.get(field_name) or 0))
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                values.append(value)
        if not values:
            return ""
        return f" / settle_ms={max(values)}"


arbitrage_execution_plan_service = ArbitrageExecutionPlanService()
