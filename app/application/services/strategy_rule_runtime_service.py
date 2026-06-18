"""Normalize strategy rule semantics for runtime decisions without changing page payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class StrategyRuleRuntimeView:
    rule_id: int
    strategy_type: str
    open_threshold: float
    close_threshold: float
    stop_loss_price_diff: float
    max_pairs: int
    order_amount_usdt: float
    max_position_quantity: float
    order_interval_seconds: int


class StrategyRuleRuntimeService:
    """Interprets persisted rule fields using the latest product semantics.

    The current page still submits legacy field names. We keep those names stable,
    but the execution side treats them as:
    - funding `annualized_rate_threshold` => open net funding threshold
    - spread `spread_rate_threshold` => open spread-rate threshold
    - `max_spread_rate_threshold` => absolute price-diff limit / stop loss
    - `max_position_usdt` => single-leg quantity cap
    """

    def build_runtime_view(self, rule_row: Dict[str, Any]) -> StrategyRuleRuntimeView:
        strategy_type = str(rule_row.get("strategy_type") or "").strip().lower()
        order_amount_usdt = self._float(rule_row.get("order_amount_usdt"))
        max_position_quantity = self._float(rule_row.get("max_position_usdt"))
        if max_position_quantity <= 0:
            max_position_quantity = order_amount_usdt

        if strategy_type == "funding":
            open_threshold = self._float(rule_row.get("annualized_rate_threshold"))
            close_threshold = self._float(rule_row.get("min_net_funding_rate_threshold"))
        else:
            open_threshold = self._float(rule_row.get("spread_rate_threshold"))
            close_threshold = self._float(rule_row.get("min_close_spread_rate_threshold"))

        return StrategyRuleRuntimeView(
            rule_id=int(rule_row.get("id") or 0),
            strategy_type=strategy_type,
            open_threshold=open_threshold,
            close_threshold=close_threshold,
            stop_loss_price_diff=self._float(rule_row.get("max_spread_rate_threshold")),
            max_pairs=max(0, int(rule_row.get("max_pairs") or 0)),
            order_amount_usdt=order_amount_usdt,
            max_position_quantity=max_position_quantity,
            order_interval_seconds=max(0, int(rule_row.get("order_interval_seconds") or 0)),
        )

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


strategy_rule_runtime_service = StrategyRuleRuntimeService()

__all__ = [
    "StrategyRuleRuntimeService",
    "StrategyRuleRuntimeView",
    "strategy_rule_runtime_service",
]
