"""Monitor opportunities and create arbitrage execution records."""

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
from app.infrastructure.cache import market_runtime_cache, redis_runtime_support
from app.infrastructure.persistence.account_repository import account_repository


logger = logging.getLogger(__name__)


class ArbitrageOpportunityMonitorService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._interval_seconds = strategy_risk_config.opportunity_monitor_interval_seconds
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
        strategy_type = str(strategy_rule.get("strategy_type") or "").strip().lower()
        evaluation_context = strategy_open_candidate_service.build_evaluation_context(
            user_id=user_id,
            channel=strategy_type,
            rule_rows=[strategy_rule],
        )

        created_count = 0
        created_pair_keys: set[str] = set()
        for opportunity in opportunity_rows:
            pair_key = self._build_pair_key(strategy_rule, opportunity)
            if not pair_key or pair_key in created_pair_keys:
                continue

            if not self._should_open(user_id, strategy_rule, opportunity, evaluation_context):
                continue
            result = arbitrage_execution_plan_service.create_open_execution(
                user_id=user_id,
                strategy_rule=strategy_rule,
                opportunity=opportunity,
            )
            if result is None:
                continue

            created_pair_keys.add(pair_key)
            created_count += 1
            evaluation_context = strategy_open_candidate_service.build_evaluation_context(
                user_id=user_id,
                channel=strategy_type,
                rule_rows=[strategy_rule],
            )
            monitor_center_service.add_log(
                self._monitor_key,
                "info",
                f"用户 {user_id} 策略 {strategy_rule.get('name') or '--'} 已生成执行 #{result.execution_id}",
            )

        return created_count

    def _should_open(
        self,
        user_id: int,
        strategy_rule: Dict[str, Any],
        opportunity: Dict[str, Any],
        evaluation_context: Any,
    ) -> bool:
        strategy_type = str(strategy_rule.get("strategy_type") or "").strip().lower()
        result = strategy_open_candidate_service.evaluate_row(
            user_id=user_id,
            channel=strategy_type,
            row=opportunity,
            context=evaluation_context,
        )
        return result.is_candidate

    def _build_pair_key(self, strategy_rule: Dict[str, Any], opportunity: Dict[str, Any]) -> str:
        market_pair_key = str(opportunity.get("market_pair_key") or "").strip().lower()
        if market_pair_key:
            return f"{int(strategy_rule.get('id') or 0)}:{market_pair_key}"

        left_exchange_code = str(opportunity.get("left_exchange_code") or "").strip().lower()
        right_exchange_code = str(opportunity.get("right_exchange_code") or "").strip().lower()
        ordered_codes = sorted(code for code in [left_exchange_code, right_exchange_code] if code)
        return f"{int(strategy_rule.get('id') or 0)}:{opportunity.get('symbol') or ''}:{':'.join(ordered_codes)}"

    def _load_opportunity_rows(self, *, channel: str, user_id: int) -> List[Dict[str, Any]]:
        state = market_runtime_cache.get_public_rows_state(channel)
        if state is None:
            return []
        rows = [
            dict(row)
            for row in list(state.rows)
            if isinstance(row, dict)
            and strategy_open_candidate_service.is_trading_status_normal(row)
        ]
        return opportunity_user_overlay_service.enrich_execution_rows(
            user_id=user_id,
            channel=channel,
            rows=rows,
        )

    def _cooldown_key(self, *, user_id: int, pair_key: str) -> str:
        return f"arbitrage:cooldown:user:{int(user_id)}:{pair_key}"

    def _is_in_cooldown(self, *, user_id: int, pair_key: str) -> bool:
        payload = redis_runtime_support.get_json(self._cooldown_key(user_id=user_id, pair_key=pair_key))
        if not isinstance(payload, dict):
            return False
        until_at = redis_runtime_support.parse_datetime(payload.get("until_at"))
        return bool(until_at and until_at > datetime.now())

    def mark_pair_cooldown(self, *, user_id: int, pair_key: str, seconds: int | None = None) -> None:
        cooldown_seconds = int(seconds or strategy_risk_config.failed_open_cooldown_seconds)
        until_at = datetime.now() + timedelta(seconds=max(1, cooldown_seconds))
        redis_runtime_support.set_json(
            self._cooldown_key(user_id=user_id, pair_key=pair_key),
            {"until_at": until_at},
            ttl_seconds=max(1, cooldown_seconds),
        )


arbitrage_opportunity_monitor_service = ArbitrageOpportunityMonitorService()
