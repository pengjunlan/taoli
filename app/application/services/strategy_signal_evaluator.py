"""Strategy signal and risk calculations shared by display and execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Dict, List

from app.application.services.strategy_execution_quality_service import strategy_execution_quality_service
from app.application.services.funding_fee_receipt_service import funding_fee_receipt_service
from app.application.services.strategy_risk_config import strategy_risk_config
from app.application.services.strategy_rule_runtime_service import StrategyRuleRuntimeView


@dataclass(frozen=True)
class StrategySignalResult:
    is_match: bool
    reason: str = ""
    blocked_reason: str = ""
    expected_net_profit_percent: float = 0.0


class StrategySignalEvaluator:
    def evaluate_open(
        self,
        *,
        channel: str,
        row: Dict[str, Any],
        rule: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
    ) -> StrategySignalResult:
        max_spread = runtime_rule.stop_loss_price_diff
        price_diff = self._parse_float(row.get("price_diff_value"), fallback=row.get("price_diff"))
        price_diff_percent = self.resolve_price_diff_percent(channel=channel, row=row)
        if max_spread > 0 and price_diff_percent > max_spread:
            return StrategySignalResult(False, blocked_reason="max_spread_exceeded")

        if channel == "funding":
            return self._evaluate_funding_signal(
                row=row,
                rule=rule,
                runtime_rule=runtime_rule,
                price_diff=price_diff,
                price_diff_percent=price_diff_percent,
            )
        if channel == "spread":
            return self._evaluate_spread_signal(
                row=row,
                rule=rule,
                runtime_rule=runtime_rule,
                price_diff=price_diff,
                price_diff_percent=price_diff_percent,
            )
        return StrategySignalResult(False, blocked_reason="unsupported_strategy_type")

    def evaluate_close_reason(
        self,
        *,
        strategy_type: str,
        execution_row: Dict[str, Any],
        opportunity: Dict[str, Any],
        rule: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
    ) -> str:
        max_spread = runtime_rule.stop_loss_price_diff
        price_diff = self.resolve_price_diff_percent(channel=strategy_type, row=opportunity)
        take_profit = self._parse_float(rule.get("take_profit_threshold"))
        estimated_net_profit = self.estimate_current_profit_percent(
            execution_row=execution_row,
            opportunity=opportunity,
            strategy_type=strategy_type,
        )
        if take_profit > 0 and estimated_net_profit >= take_profit:
            return f"[take_profit] 估算净收益 {estimated_net_profit:.4f}% 已达到止盈阈值 {take_profit:.4f}%，触发止盈平仓"

        if strategy_type == "funding":
            net_rate = self.resolve_funding_close_metric(execution_row=execution_row, opportunity=opportunity)
            if self.is_funding_direction_reversed(execution_row=execution_row, opportunity=opportunity):
                return f"[stop_loss] 资金费方向已反转，当前方向净资金费 {net_rate:.4f}%，触发止损平仓"
            if max_spread > 0 and price_diff > max_spread:
                return f"[stop_loss] 价格差达到 {price_diff:.4f}%，超过最大价差 {max_spread:.4f}%，触发止损平仓"
            funding_settlement_passed = self.is_funding_settlement_passed(
                execution_row=execution_row,
                opportunity=opportunity,
            )
            if funding_settlement_passed and net_rate < runtime_rule.close_threshold:
                return f"[normal_close] 净资金费率回落到 {net_rate:.4f}%，低于最小净资金费率 {runtime_rule.close_threshold:.4f}%，触发正常平仓"
            return ""

        if strategy_type == "spread":
            latest_spread = self.resolve_spread_close_metric(execution_row=execution_row, opportunity=opportunity)
            funding_carry = self.spread_funding_carry_percent(opportunity)
            max_funding_cost = self._parse_float(rule.get("max_funding_cost"))
            if max_funding_cost > 0 and funding_carry < -max_funding_cost:
                return f"[stop_loss] 资金费 Carry {funding_carry:.4f}% 已低于最大资金费成本 -{max_funding_cost:.4f}%，触发止损平仓"
            if max_spread > 0 and price_diff > max_spread:
                return f"[stop_loss] 价格差达到 {price_diff:.4f}%，超过最大价差 {max_spread:.4f}%，触发止损平仓"
            if latest_spread <= runtime_rule.close_threshold:
                return f"[normal_close] 价差回落到 {latest_spread:.4f}%，低于最小平仓价差 {runtime_rule.close_threshold:.4f}%，触发正常平仓"
            return ""

        return ""

    def evaluate_liquidity(self, *, row: Dict[str, Any], runtime_rule: StrategyRuleRuntimeView) -> str:
        order_amount = float(runtime_rule.order_amount_usdt or 0)
        if order_amount <= 0:
            return "order_amount_invalid"

        left_price = self._parse_float(row.get("left_price_value"))
        right_price = self._parse_float(row.get("right_price_value"))
        if left_price <= 0 or right_price <= 0:
            return "price_missing"

        left_quote_volume = self._parse_float(row.get("left_quote_volume_value"))
        right_quote_volume = self._parse_float(row.get("right_quote_volume_value"))
        min_quote_volume = order_amount * strategy_risk_config.min_quote_volume_multiplier
        if min_quote_volume > 0:
            if left_quote_volume > 0 and left_quote_volume < min_quote_volume:
                return "left_depth_insufficient"
            if right_quote_volume > 0 and right_quote_volume < min_quote_volume:
                return "right_depth_insufficient"

        left_bid_ask = self._parse_float(row.get("left_bid_ask_spread_percent_value"))
        right_bid_ask = self._parse_float(row.get("right_bid_ask_spread_percent_value"))
        max_bid_ask = max(0.0, strategy_risk_config.max_bid_ask_spread_percent)
        if max_bid_ask > 0:
            if left_bid_ask > max_bid_ask:
                return "left_slippage_too_large"
            if right_bid_ask > max_bid_ask:
                return "right_slippage_too_large"

        depth_block, order_book_slippage = strategy_execution_quality_service.evaluate_depth_and_slippage(
            row=row,
            runtime_rule=runtime_rule,
        )
        if depth_block:
            return depth_block
        if order_book_slippage > 0:
            row["order_book_slippage_percent_value"] = order_book_slippage
        return ""

    def estimate_current_profit_percent(
        self,
        *,
        execution_row: Dict[str, Any],
        opportunity: Dict[str, Any],
        strategy_type: str,
    ) -> float:
        if strategy_type == "funding":
            entry_spread = self._parse_percent(execution_row.get("trigger_metric_risk"))
            current_spread = self.funding_signed_spread_percent(opportunity)
            current_net_rate = self.resolve_funding_close_metric(
                execution_row=execution_row,
                opportunity=opportunity,
            )
            return max(0.0, entry_spread - current_spread) + max(0.0, current_net_rate)

        entry_spread = self._parse_percent(execution_row.get("trigger_metric_primary"))
        current_spread = self.resolve_spread_close_metric(
            execution_row=execution_row,
            opportunity=opportunity,
        )
        funding_carry = self.spread_funding_carry_percent(opportunity)
        return max(0.0, entry_spread - current_spread) + funding_carry

    def is_funding_direction_reversed(self, *, execution_row: Dict[str, Any], opportunity: Dict[str, Any]) -> bool:
        left_exchange = str(execution_row.get("left_exchange_code") or "").strip().lower()
        right_exchange = str(execution_row.get("right_exchange_code") or "").strip().lower()
        market_left_exchange = str(opportunity.get("market_left_exchange_code") or "").strip().lower()
        market_right_exchange = str(opportunity.get("market_right_exchange_code") or "").strip().lower()
        if not left_exchange or not right_exchange:
            return False
        if left_exchange == market_left_exchange and right_exchange == market_right_exchange:
            return self._parse_float(opportunity.get("left_long_right_short_net_rate_value")) < 0
        if left_exchange == market_right_exchange and right_exchange == market_left_exchange:
            return self._parse_float(opportunity.get("right_long_left_short_net_rate_value")) < 0
        return self.resolve_funding_close_metric(execution_row=execution_row, opportunity=opportunity) < 0

    def is_funding_settlement_passed(self, *, execution_row: Dict[str, Any], opportunity: Dict[str, Any]) -> bool:
        recorded_settlement_ms = self._extract_recorded_settlement_ms(execution_row)
        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000
        if recorded_settlement_ms > 0:
            return funding_fee_receipt_service.has_confirmed_or_gracefully_passed(
                execution_row=execution_row,
                settlement_ms=recorded_settlement_ms,
            )

        created_at = execution_row.get("created_at")
        if not isinstance(created_at, datetime):
            return False
        settlement_values = self.funding_settlement_values(opportunity)
        if not settlement_values:
            return False
        created_ms = created_at.timestamp() * 1000
        future_values = [value for value in settlement_values if value > created_ms]
        if not future_values:
            return False
        settlement_ms = max(future_values)
        if now_ms <= settlement_ms:
            return False
        return funding_fee_receipt_service.has_confirmed_or_gracefully_passed(
            execution_row=execution_row,
            settlement_ms=settlement_ms,
        )

    def _extract_recorded_settlement_ms(self, execution_row: Dict[str, Any]) -> float:
        for field_name in ("trigger_metric_secondary", "trigger_reason"):
            text = str(execution_row.get(field_name) or "")
            match = re.search(r"settle_ms=(\d+)", text)
            if not match:
                continue
            try:
                return float(match.group(1))
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def is_within_funding_open_window(self, *, row: Dict[str, Any], rule: Dict[str, Any]) -> bool:
        start_minutes = max(0, int(rule.get("funding_open_window_start_minutes") or 0))
        end_minutes = max(0, int(rule.get("funding_open_window_end_minutes") or 0))
        if start_minutes <= 0 and end_minutes <= 0:
            return True

        settlement_values = self.funding_settlement_values(row)
        if not settlement_values:
            return False

        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000
        skew_minutes = max(0, int(strategy_risk_config.max_funding_settlement_skew_minutes or 0))
        if len(settlement_values) > 1 and skew_minutes > 0:
            if (max(settlement_values) - min(settlement_values)) / 60000 > skew_minutes:
                return False

        for settlement_at_ms in settlement_values:
            minutes_to_settlement = (settlement_at_ms - now_ms) / 60000
            if minutes_to_settlement < 0:
                return False
            if start_minutes > 0 and minutes_to_settlement > start_minutes:
                return False
            if end_minutes > 0 and minutes_to_settlement <= end_minutes:
                return False
        return True

    def funding_settlement_values(self, row: Dict[str, Any]) -> List[float]:
        values = [
            self._parse_float(row.get("long_settlement_at_ms")),
            self._parse_float(row.get("short_settlement_at_ms")),
        ]
        values = [value for value in values if value > 0]
        if values:
            return values
        fallback = self._parse_float(row.get("settlement_at_ms"))
        return [fallback] if fallback > 0 else []

    def funding_signed_spread_percent(self, row: Dict[str, Any]) -> float:
        long_price = self._parse_float(row.get("left_price_value"))
        short_price = self._parse_float(row.get("right_price_value"))
        if long_price <= 0 or short_price <= 0:
            return 0.0
        return ((short_price - long_price) / long_price) * 100

    def spread_funding_carry_percent(self, row: Dict[str, Any]) -> float:
        if "funding_carry_value" in row:
            return self._parse_float(row.get("funding_carry_value"))
        buy_rate = self._parse_float(row.get("buy_funding_rate_value"), fallback=row.get("buy_funding_rate"))
        sell_rate = self._parse_float(row.get("sell_funding_rate_value"), fallback=row.get("sell_funding_rate"))
        if buy_rate != 0 or sell_rate != 0:
            return sell_rate - buy_rate
        return self._parse_float(row.get("net_rate_value"), fallback=row.get("net_rate"))

    def resolve_price_diff_percent(self, *, channel: str, row: Dict[str, Any]) -> float:
        cross_exchange_gap = self._parse_float(row.get("cross_exchange_price_gap_percent_value"))
        if cross_exchange_gap > 0:
            return abs(cross_exchange_gap)
        if channel == "funding":
            return abs(self.funding_signed_spread_percent(row))
        if channel == "spread":
            latest_spread = self._parse_float(row.get("latest_spread_value"), fallback=row.get("latest_spread"))
            return abs(latest_spread)
        return 0.0

    def resolve_funding_close_metric(self, *, execution_row: Dict[str, Any], opportunity: Dict[str, Any]) -> float:
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

    def resolve_spread_close_metric(self, *, execution_row: Dict[str, Any], opportunity: Dict[str, Any]) -> float:
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

    def _evaluate_funding_signal(
        self,
        *,
        row: Dict[str, Any],
        rule: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
        price_diff: float,
        price_diff_percent: float,
    ) -> StrategySignalResult:
        net_rate = self._parse_float(row.get("net_rate_value"), fallback=row.get("net_rate"))
        if net_rate <= runtime_rule.open_threshold:
            return StrategySignalResult(False, blocked_reason="funding_threshold_not_met")

        if not self.is_within_funding_open_window(row=row, rule=rule):
            return StrategySignalResult(False, blocked_reason="funding_open_window_not_matched")

        spread_percent = self.funding_signed_spread_percent(row)
        if spread_percent < 0:
            return StrategySignalResult(False, blocked_reason="funding_spread_not_resonant")
        resonance_min = self._parse_float(rule.get("funding_spread_resonance_min"))
        if resonance_min > 0 and spread_percent < resonance_min:
            return StrategySignalResult(False, blocked_reason="funding_spread_resonance_below_min")

        liquidity_block = self.evaluate_liquidity(row=row, runtime_rule=runtime_rule)
        if liquidity_block:
            return StrategySignalResult(False, blocked_reason=liquidity_block)

        fee_cost = self._fee_cost_percent(row=row, prefixes=("long", "short"))
        slippage_cost = self._slippage_cost_percent(row=row)
        expected_net = net_rate + max(spread_percent, 0.0) - fee_cost - slippage_cost
        min_net_profit = self._parse_float(rule.get("min_net_profit_threshold"))
        if min_net_profit > 0 and expected_net < min_net_profit:
            return StrategySignalResult(False, blocked_reason="min_net_profit_not_met", expected_net_profit_percent=expected_net)

        return StrategySignalResult(
            True,
            reason=(
                f"funding net_rate {net_rate:.4f}% > "
                f"{runtime_rule.open_threshold:.4f}%, spread {spread_percent:.4f}%, "
                f"fee {fee_cost:.4f}%, slippage {slippage_cost:.4f}%, "
                f"expected_net {expected_net:.4f}%, "
                f"price_diff {price_diff:.6f}, price_diff_percent {price_diff_percent:.4f}%"
            ),
            expected_net_profit_percent=expected_net,
        )

    def _evaluate_spread_signal(
        self,
        *,
        row: Dict[str, Any],
        rule: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
        price_diff: float,
        price_diff_percent: float,
    ) -> StrategySignalResult:
        latest_spread = self._parse_float(row.get("latest_spread_value"), fallback=row.get("latest_spread"))
        if latest_spread < runtime_rule.open_threshold:
            return StrategySignalResult(False, blocked_reason="spread_threshold_not_met")

        net_spread = self._parse_float(row.get("net_spread_value"), fallback=row.get("net_spread"))
        net_spread_threshold = self._parse_float(rule.get("net_spread_threshold"))
        if net_spread_threshold > 0 and net_spread < net_spread_threshold:
            return StrategySignalResult(False, blocked_reason="net_spread_threshold_not_met")

        funding_carry = self.spread_funding_carry_percent(row)
        max_funding_cost = self._parse_float(rule.get("max_funding_cost"))
        if max_funding_cost > 0 and funding_carry < -max_funding_cost:
            return StrategySignalResult(False, blocked_reason="max_funding_cost_exceeded")

        funding_carry_min = self._parse_float(rule.get("funding_carry_min"))
        if funding_carry_min > 0 and funding_carry < funding_carry_min:
            return StrategySignalResult(False, blocked_reason="funding_carry_below_min")

        liquidity_block = self.evaluate_liquidity(row=row, runtime_rule=runtime_rule)
        if liquidity_block:
            return StrategySignalResult(False, blocked_reason=liquidity_block)

        slippage_cost = self._slippage_cost_percent(row=row)
        expected_net = net_spread + funding_carry - slippage_cost
        min_net_profit = self._parse_float(rule.get("min_net_profit_threshold"))
        if min_net_profit > 0 and expected_net < min_net_profit:
            return StrategySignalResult(False, blocked_reason="min_net_profit_not_met", expected_net_profit_percent=expected_net)

        return StrategySignalResult(
            True,
            reason=(
                f"spread latest_spread {latest_spread:.4f}% >= "
                f"{runtime_rule.open_threshold:.4f}%, net_spread {net_spread:.4f}%, "
                f"carry {funding_carry:.4f}%, slippage {slippage_cost:.4f}%, "
                f"expected_net {expected_net:.4f}%, "
                f"price_diff {price_diff:.6f}, price_diff_percent {price_diff_percent:.4f}%"
            ),
            expected_net_profit_percent=expected_net,
        )

    def _fee_cost_percent(self, *, row: Dict[str, Any], prefixes: tuple[str, str]) -> float:
        total = 0.0
        for prefix in prefixes:
            total += self._parse_float(row.get(f"{prefix}_taker_fee_rate_value"), fallback=row.get(f"{prefix}_fee_rate"))
        return total

    def _slippage_cost_percent(self, *, row: Dict[str, Any]) -> float:
        order_book_slippage = self._parse_float(row.get("order_book_slippage_percent_value"))
        if order_book_slippage > 0:
            return order_book_slippage
        return max(0.0, self._parse_float(row.get("left_bid_ask_spread_percent_value"))) + max(
            0.0,
            self._parse_float(row.get("right_bid_ask_spread_percent_value")),
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


strategy_signal_evaluator = StrategySignalEvaluator()


__all__ = [
    "StrategySignalEvaluator",
    "StrategySignalResult",
    "strategy_signal_evaluator",
]
