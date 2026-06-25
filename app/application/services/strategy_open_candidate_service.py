"""Per-user open-candidate evaluation for opportunity display rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from app.application.services.strategy_rule_runtime_service import (
    StrategyRuleRuntimeView,
    strategy_rule_runtime_service,
)
from app.infrastructure.persistence import arbitrage_execution_repository
from app.infrastructure.persistence.account_repository import account_repository


ACTIVE_OPEN_STATUSES = {"pending", "created", "processing", "opening", "open", "closing"}
TERMINAL_BLOCK_STATUSES = {"closed"}


@dataclass(frozen=True)
class OpenCandidateResult:
    is_candidate: bool
    rule_id: int = 0
    rule_name: str = ""
    reason: str = ""
    blocked_reason: str = ""


class StrategyOpenCandidateService:
    """Marks rows that satisfy current user's new-open conditions.

    This is intentionally read-only: shared market rows are copied before adding
    user-specific fields. The same service is the future seam for real open/close
    execution so page highlighting and execution decisions do not drift apart.
    """

    def enrich_rows(
        self,
        *,
        user_id: int,
        channel: str,
        rows: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized_channel = str(channel or "").strip().lower()
        display_rows = [dict(row) for row in rows if isinstance(row, dict)]
        if not display_rows:
            return []

        rule_rows = self._rule_rows(user_id=user_id, channel=normalized_channel)
        if not rule_rows:
            return [
                self._apply_result(row, OpenCandidateResult(False, blocked_reason="no_strategy_rule"))
                for row in display_rows
            ]

        rule_views = {
            int(rule.get("id") or 0): strategy_rule_runtime_service.build_runtime_view(rule)
            for rule in rule_rows
        }
        rule_state = self._build_rule_state(user_id=user_id, rule_rows=rule_rows)
        account_available = self._build_account_available_lookup(user_id=user_id)

        enriched_rows: List[Dict[str, Any]] = []
        for row in display_rows:
            result = self.evaluate_row(
                user_id=user_id,
                channel=normalized_channel,
                row=row,
                rule_rows=rule_rows,
                rule_views=rule_views,
                rule_state=rule_state,
                account_available=account_available,
            )
            enriched_rows.append(self._apply_result(row, result))
        return enriched_rows

    def evaluate_row(
        self,
        *,
        user_id: int,
        channel: str,
        row: Dict[str, Any],
        rule_rows: List[Dict[str, Any]],
        rule_views: Dict[int, StrategyRuleRuntimeView],
        rule_state: Dict[int, Dict[str, Any]],
        account_available: Dict[int, float],
    ) -> OpenCandidateResult:
        if not bool(row.get("execution_ready")):
            return OpenCandidateResult(False, blocked_reason="execution_not_ready")

        pair_block = self._evaluate_user_pair_state(user_id=user_id, row=row)
        if pair_block:
            return OpenCandidateResult(False, blocked_reason=pair_block)

        first_blocked_reason = ""
        for rule in rule_rows:
            rule_id = int(rule.get("id") or 0)
            runtime_rule = rule_views.get(rule_id)
            if runtime_rule is None:
                continue

            signal_reason = self._evaluate_signal(channel=channel, row=row, rule=rule, runtime_rule=runtime_rule)
            if not signal_reason:
                continue

            state_block = self._evaluate_rule_state(
                row=row,
                runtime_rule=runtime_rule,
                state=rule_state.get(rule_id, {}),
                account_available=account_available,
            )
            if state_block:
                if not first_blocked_reason:
                    first_blocked_reason = state_block
                continue

            return OpenCandidateResult(
                True,
                rule_id=rule_id,
                rule_name=str(rule.get("name") or ""),
                reason=signal_reason,
            )

        return OpenCandidateResult(False, blocked_reason=first_blocked_reason or "signal_not_matched")

    def _evaluate_signal(
        self,
        *,
        channel: str,
        row: Dict[str, Any],
        rule: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
    ) -> str:
        max_spread = runtime_rule.stop_loss_price_diff
        price_diff = self._parse_float(row.get("price_diff_value"), fallback=row.get("price_diff"))
        if max_spread > 0 and price_diff > max_spread:
            return ""

        if channel == "funding":
            return self._evaluate_funding_signal(row=row, rule=rule, runtime_rule=runtime_rule, price_diff=price_diff)
        if channel == "spread":
            return self._evaluate_spread_signal(row=row, rule=rule, runtime_rule=runtime_rule, price_diff=price_diff)
        return ""

    def _evaluate_funding_signal(
        self,
        *,
        row: Dict[str, Any],
        rule: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
        price_diff: float,
    ) -> str:
        net_rate = self._parse_float(row.get("net_rate_value"), fallback=row.get("net_rate"))
        if net_rate <= runtime_rule.open_threshold:
            return ""

        if not self._is_within_funding_open_window(row=row, rule=rule):
            return ""

        spread_percent = abs(self._parse_float(row.get("spread_value"), fallback=row.get("spread")))
        resonance_min = self._parse_float(rule.get("funding_spread_resonance_min"))
        if resonance_min > 0 and spread_percent < resonance_min:
            return ""

        min_net_profit = self._parse_float(rule.get("min_net_profit_threshold"))
        if min_net_profit > 0 and net_rate + spread_percent < min_net_profit:
            return ""

        return (
            f"funding net_rate {net_rate:.4f}% > "
            f"{runtime_rule.open_threshold:.4f}%, price_diff {price_diff:.6f}"
        )

    def _evaluate_spread_signal(
        self,
        *,
        row: Dict[str, Any],
        rule: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
        price_diff: float,
    ) -> str:
        latest_spread = self._parse_float(row.get("latest_spread_value"), fallback=row.get("latest_spread"))
        if latest_spread < runtime_rule.open_threshold:
            return ""

        net_spread_threshold = self._parse_float(rule.get("net_spread_threshold"))
        if net_spread_threshold > 0:
            net_spread = self._parse_float(row.get("net_spread_value"), fallback=row.get("net_spread"))
            if net_spread < net_spread_threshold:
                return ""

        funding_carry_min = self._parse_float(rule.get("funding_carry_min"))
        if funding_carry_min > 0:
            funding_carry = self._parse_float(row.get("net_rate_value"), fallback=row.get("net_rate"))
            if funding_carry < funding_carry_min:
                return ""

        min_net_profit = self._parse_float(rule.get("min_net_profit_threshold"))
        if min_net_profit > 0:
            net_spread = self._parse_float(row.get("net_spread_value"), fallback=row.get("net_spread"))
            funding_carry = self._parse_float(row.get("net_rate_value"), fallback=row.get("net_rate"))
            if net_spread + max(funding_carry, 0.0) < min_net_profit:
                return ""

        return (
            f"spread latest_spread {latest_spread:.4f}% >= "
            f"{runtime_rule.open_threshold:.4f}%, price_diff {price_diff:.6f}"
        )

    def _evaluate_user_pair_state(self, *, user_id: int, row: Dict[str, Any]) -> str:
        pair_suffix = self._build_pair_suffix(row=row)
        if not pair_suffix:
            return "pair_key_missing"

        latest_open = arbitrage_execution_repository.get_latest_open_execution_by_user_pair_suffix(
            user_id=user_id,
            pair_suffix=pair_suffix,
        )
        if latest_open is not None:
            latest_status = str(latest_open.get("status") or "").strip().lower()
            if latest_status in ACTIVE_OPEN_STATUSES:
                return "pair_has_active_execution"
            if latest_status in TERMINAL_BLOCK_STATUSES:
                return "pair_has_closed_execution"

        if arbitrage_execution_repository.has_open_close_execution_by_user_pair_suffix(
            user_id=user_id,
            pair_suffix=pair_suffix,
        ):
            return "pair_has_closing_execution"

        return ""

    def _evaluate_rule_state(
        self,
        *,
        row: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
        state: Dict[str, Any],
        account_available: Dict[int, float],
    ) -> str:
        max_pairs = runtime_rule.max_pairs
        active_pair_count = int(state.get("active_pair_count") or 0)
        if max_pairs > 0 and active_pair_count >= max_pairs:
            return "max_pairs_reached"
        if not self._has_order_capacity(
            row=row,
            order_amount=runtime_rule.order_amount_usdt,
            account_available=account_available,
        ):
            return "insufficient_available_balance"
        return ""

    def _build_rule_state(self, *, user_id: int, rule_rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
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

    def _build_account_available_lookup(self, *, user_id: int) -> Dict[int, float]:
        result: Dict[int, float] = {}
        for row in account_repository.list_active_accounts_with_address_by_user_id(user_id):
            account_id = int(row.get("id") or 0)
            if account_id <= 0:
                continue
            result[account_id] = self._parse_float(row.get("current_available_amount"))
        return result

    def _rule_rows(self, *, user_id: int, channel: str) -> List[Dict[str, Any]]:
        return [
            row
            for row in account_repository.list_strategy_rules_by_user_id(user_id)
            if str(row.get("strategy_type") or "").strip().lower() == channel
        ]

    def _has_order_capacity(
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

    def _apply_result(self, row: Dict[str, Any], result: OpenCandidateResult) -> Dict[str, Any]:
        item = dict(row)
        item["open_candidate"] = bool(result.is_candidate)
        item["open_candidate_type"] = "open" if result.is_candidate else ""
        item["open_candidate_rule_id"] = int(result.rule_id or 0)
        item["open_candidate_rule_name"] = result.rule_name
        item["open_candidate_reason"] = result.reason
        item["open_candidate_blocked_reason"] = result.blocked_reason
        return item

    def _build_pair_suffix(self, *, row: Dict[str, Any]) -> str:
        market_pair_key = str(row.get("market_pair_key") or "").strip().lower()
        if market_pair_key:
            return market_pair_key

        left_exchange_code = str(row.get("left_exchange_code") or "").strip().lower()
        right_exchange_code = str(row.get("right_exchange_code") or "").strip().lower()
        ordered_codes = sorted(code for code in (left_exchange_code, right_exchange_code) if code)
        symbol = str(row.get("symbol") or "").strip()
        return f"{symbol}:{':'.join(ordered_codes)}"

    def _is_within_funding_open_window(self, *, row: Dict[str, Any], rule: Dict[str, Any]) -> bool:
        start_minutes = max(0, int(rule.get("funding_open_window_start_minutes") or 0))
        end_minutes = max(0, int(rule.get("funding_open_window_end_minutes") or 0))
        if start_minutes <= 0 and end_minutes <= 0:
            return True

        settlement_at_ms = self._parse_float(row.get("settlement_at_ms"))
        if settlement_at_ms <= 0:
            return False

        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000
        minutes_to_settlement = (settlement_at_ms - now_ms) / 60000
        if minutes_to_settlement < 0:
            return False
        if start_minutes > 0 and minutes_to_settlement > start_minutes:
            return False
        if end_minutes > 0 and minutes_to_settlement <= end_minutes:
            return False
        return True

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


strategy_open_candidate_service = StrategyOpenCandidateService()

__all__ = [
    "OpenCandidateResult",
    "StrategyOpenCandidateService",
    "strategy_open_candidate_service",
]
