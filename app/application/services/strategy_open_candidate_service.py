"""Per-user open-candidate evaluation for opportunity display rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from app.application.services.strategy_rule_runtime_service import (
    StrategyRuleRuntimeView,
    strategy_rule_runtime_service,
)
from app.application.services.funding_runtime_state_service import funding_runtime_state_service
from app.application.services.spread_runtime_state_service import spread_runtime_state_service
from app.application.services.strategy_position_guard import strategy_position_guard
from app.application.services.strategy_signal_evaluator import strategy_signal_evaluator
from app.infrastructure.persistence.account_repository import account_repository


@dataclass(frozen=True)
class OpenCandidateResult:
    is_candidate: bool
    rule_id: int = 0
    rule_name: str = ""
    reason: str = ""
    blocked_reason: str = ""


@dataclass(frozen=True)
class OpenEvaluationContext:
    rule_rows: List[Dict[str, Any]]
    rule_views: Dict[int, StrategyRuleRuntimeView]
    rule_state: Dict[int, Dict[str, Any]]
    pair_notional: Dict[str, float]
    account_available: Dict[int, float]


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

        context = self.build_evaluation_context(user_id=user_id, channel=normalized_channel)
        if not context.rule_rows:
            return [
                self._apply_result(row, OpenCandidateResult(False, blocked_reason="no_strategy_rule"))
                for row in display_rows
            ]

        enriched_rows: List[Dict[str, Any]] = []
        for row in display_rows:
            result = self.evaluate_row(
                user_id=user_id,
                channel=normalized_channel,
                row=row,
                context=context,
            )
            enriched_rows.append(self._apply_result(row, result))
        return enriched_rows

    def build_evaluation_context(
        self,
        *,
        user_id: int,
        channel: str,
        rule_rows: Iterable[Dict[str, Any]] | None = None,
    ) -> OpenEvaluationContext:
        normalized_channel = str(channel or "").strip().lower()
        selected_rules = [
            dict(row)
            for row in (rule_rows if rule_rows is not None else self._rule_rows(user_id=user_id, channel=normalized_channel))
            if isinstance(row, dict)
            and str(row.get("strategy_type") or "").strip().lower() == normalized_channel
        ]
        rule_views = {
            int(rule.get("id") or 0): strategy_rule_runtime_service.build_runtime_view(rule)
            for rule in selected_rules
        }
        return OpenEvaluationContext(
            rule_rows=selected_rules,
            rule_views=rule_views,
            rule_state=strategy_position_guard.build_rule_state(user_id=user_id, rule_rows=selected_rules),
            pair_notional=strategy_position_guard.build_pair_notional_lookup(user_id=user_id, rule_rows=selected_rules),
            account_available=strategy_position_guard.build_account_available_lookup(user_id=user_id),
        )

    def evaluate_row(
        self,
        *,
        user_id: int,
        channel: str,
        row: Dict[str, Any],
        context: OpenEvaluationContext,
    ) -> OpenCandidateResult:
        if not self.is_trading_status_normal(row):
            return OpenCandidateResult(False, blocked_reason="row_status_not_normal")
        if not bool(row.get("execution_ready")):
            return OpenCandidateResult(False, blocked_reason="execution_not_ready")

        return self._evaluate_signal_and_guards(
            user_id=user_id,
            channel=channel,
            row=row,
            context=context,
        )

    def evaluate_display_row(
        self,
        *,
        user_id: int,
        channel: str,
        row: Dict[str, Any],
        context: OpenEvaluationContext,
    ) -> OpenCandidateResult:
        if not self.is_display_status_eligible(row):
            return OpenCandidateResult(False, blocked_reason="row_status_not_normal")
        if not self.has_required_accounts(row):
            return OpenCandidateResult(False, blocked_reason="execution_not_ready")

        return self._evaluate_signal_and_guards(
            user_id=user_id,
            channel=channel,
            row=row,
            context=context,
        )

    def _evaluate_signal_and_guards(
        self,
        *,
        user_id: int,
        channel: str,
        row: Dict[str, Any],
        context: OpenEvaluationContext,
    ) -> OpenCandidateResult:

        first_blocked_reason = ""
        for rule in context.rule_rows:
            rule_id = int(rule.get("id") or 0)
            runtime_rule = context.rule_views.get(rule_id)
            if runtime_rule is None:
                continue

            pair_block, is_existing_pair = strategy_position_guard.evaluate_rule_pair_state(
                user_id=user_id,
                row=row,
                runtime_rule=runtime_rule,
            )
            if is_existing_pair and channel == "spread":
                spread_runtime_state_service.patch_pair_state(
                    user_id=user_id,
                    rule_id=rule_id,
                    pair_key=strategy_position_guard.build_rule_pair_key(rule_id=rule_id, row=row),
                    latest_spread_value=float(row.get("latest_spread_value") or 0),
                    latest_net_spread_value=float(row.get("net_spread_value") or 0),
                )
            if is_existing_pair and channel == "funding":
                funding_runtime_state_service.patch_pair_state(
                    user_id=user_id,
                    rule_id=rule_id,
                    pair_key=strategy_position_guard.build_rule_pair_key(rule_id=rule_id, row=row),
                    latest_net_rate_value=float(row.get("net_rate_value") or 0),
                    latest_spread_value=float(row.get("spread_value") or 0),
                )
            if pair_block:
                if not first_blocked_reason:
                    first_blocked_reason = pair_block
                continue

            signal_result = strategy_signal_evaluator.evaluate_open(
                channel=channel,
                row=row,
                rule=rule,
                runtime_rule=runtime_rule,
                is_existing_pair=is_existing_pair,
            )
            if not signal_result.is_match:
                if signal_result.blocked_reason and not first_blocked_reason:
                    first_blocked_reason = signal_result.blocked_reason
                continue

            state_block = strategy_position_guard.evaluate_rule_state(
                row=row,
                runtime_rule=runtime_rule,
                state=context.rule_state.get(rule_id, {}),
                pair_notional=context.pair_notional,
                account_available=context.account_available,
                is_existing_pair=is_existing_pair,
            )
            if state_block:
                if not first_blocked_reason:
                    first_blocked_reason = state_block
                continue

            return OpenCandidateResult(
                True,
                rule_id=rule_id,
                rule_name=str(rule.get("name") or ""),
                reason=signal_result.reason,
            )

        return OpenCandidateResult(False, blocked_reason=first_blocked_reason or "signal_not_matched")

    def evaluate_execution_rule(
        self,
        *,
        user_id: int = 0,
        channel: str,
        row: Dict[str, Any],
        rule: Dict[str, Any],
        context: OpenEvaluationContext,
    ) -> OpenCandidateResult:
        if user_id > 0:
            rule_id = int(rule.get("id") or 0)
            single_rule_context = OpenEvaluationContext(
                rule_rows=[rule],
                rule_views={rule_id: context.rule_views[rule_id]} if rule_id in context.rule_views else {},
                rule_state={rule_id: context.rule_state.get(rule_id, {})},
                pair_notional=context.pair_notional,
                account_available=context.account_available,
            )
            return self.evaluate_row(
                user_id=user_id,
                channel=channel,
                row=row,
                context=single_rule_context,
            )

        return OpenCandidateResult(False, blocked_reason="user_id_missing")

    def is_trading_status_normal(self, row: Dict[str, Any]) -> bool:
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

    def is_display_status_eligible(self, row: Dict[str, Any]) -> bool:
        status_code = row.get("status_code")
        if status_code not in (None, ""):
            try:
                if int(status_code) not in (1, 2):
                    return False
            except (TypeError, ValueError):
                return False

        row_status = str(row.get("row_status") or "").strip().lower()
        if row_status in {"frozen", "missing"}:
            return False

        if bool(row.get("is_frozen")):
            return False
        if not bool(row.get("has_market_data")):
            return False
        if not bool(row.get("is_price_aligned", True)):
            return False
        return True

    def has_required_accounts(self, row: Dict[str, Any]) -> bool:
        if "has_required_accounts" in row:
            return bool(row.get("has_required_accounts"))
        return int(row.get("left_account_id") or 0) > 0 and int(row.get("right_account_id") or 0) > 0

    def _rule_rows(self, *, user_id: int, channel: str) -> List[Dict[str, Any]]:
        return [
            row
            for row in account_repository.list_strategy_rules_by_user_id(user_id)
            if str(row.get("strategy_type") or "").strip().lower() == channel
        ]

    def _apply_result(self, row: Dict[str, Any], result: OpenCandidateResult) -> Dict[str, Any]:
        item = dict(row)
        item["open_candidate"] = bool(result.is_candidate)
        item["open_candidate_type"] = "open" if result.is_candidate else ""
        item["open_candidate_rule_id"] = int(result.rule_id or 0)
        item["open_candidate_rule_name"] = result.rule_name
        item["open_candidate_reason"] = result.reason
        item["open_candidate_blocked_reason"] = result.blocked_reason
        item["matched_rule_id"] = int(result.rule_id or 0)
        item["matched_rule_name"] = result.rule_name
        item["blocked_reason"] = result.blocked_reason
        return item

strategy_open_candidate_service = StrategyOpenCandidateService()

__all__ = [
    "OpenEvaluationContext",
    "OpenCandidateResult",
    "StrategyOpenCandidateService",
    "strategy_open_candidate_service",
]
