"""Strategy rule service for rule management page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from app.application.dto.requests.strategy_requests import (
    StrategyRuleCreateRequest,
    StrategyRuleUpdateRequest,
)
from app.application.services.arbitrage_execution_plan_service import arbitrage_execution_plan_service
from app.application.services.strategy_rule_runtime_service import strategy_rule_runtime_service
from app.domain.entities import AuthUser, StrategyRule
from app.infrastructure.persistence import arbitrage_execution_repository
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import AccountNotFoundError, AccountPersistenceError, AccountValidationError


STRATEGY_TYPE_LABELS = {
    "funding": "资金费套利",
    "spread": "价差套利",
}


@dataclass(frozen=True)
class StrategyRuleResult:
    rule: StrategyRule


class StrategyRuleService:
    def list_rules_for_user(self, user_id: int) -> List[Dict[str, object]]:
        rows = account_repository.list_strategy_rules_by_user_id(user_id)
        return [self._build_rule_row(row) for row in rows]

    def get_rule_detail(self, rule_id: int, current_user: AuthUser) -> Dict[str, object]:
        row = account_repository.get_strategy_rule_by_id(rule_id, current_user.id)
        if row is None:
            raise AccountNotFoundError("规则不存在，或你无权访问该规则。")
        return self._build_rule_row(row)

    def create_rule(self, payload: StrategyRuleCreateRequest, current_user: AuthUser) -> StrategyRuleResult:
        normalized = self._normalize_payload(
            name=payload.name,
            strategy_type=payload.strategy_type,
            annualized_rate_threshold=payload.annualized_rate_threshold,
            min_net_funding_rate_threshold=payload.min_net_funding_rate_threshold,
            spread_rate_threshold=payload.spread_rate_threshold,
            open_spread_rate_max_threshold=payload.open_spread_rate_max_threshold,
            min_close_spread_rate_threshold=payload.min_close_spread_rate_threshold,
            max_spread_rate_threshold=payload.max_spread_rate_threshold,
            max_pairs=payload.max_pairs,
            order_amount_usdt=payload.order_amount_usdt,
            max_position_usdt=payload.max_position_usdt,
            order_interval_seconds=payload.order_interval_seconds,
            split_order_amount_usdt=payload.split_order_amount_usdt,
            funding_open_window_start_minutes=payload.funding_open_window_start_minutes,
            funding_open_window_end_minutes=payload.funding_open_window_end_minutes,
            funding_settlement_skew_minutes=payload.funding_settlement_skew_minutes,
            funding_spread_resonance_min=payload.funding_spread_resonance_min,
            net_spread_threshold=payload.net_spread_threshold,
            funding_carry_min=payload.funding_carry_min,
            max_funding_cost=payload.max_funding_cost,
            min_net_profit_threshold=payload.min_net_profit_threshold,
            take_profit_threshold=payload.take_profit_threshold,
            drawdown_add_step_percent=payload.drawdown_add_step_percent,
            max_hold_minutes=payload.max_hold_minutes,
            close_interval_seconds=payload.close_interval_seconds,
            close_batch_count=payload.close_batch_count,
            close_batch_ratio_percent=payload.close_batch_ratio_percent,
            single_leg_timeout_seconds=payload.single_leg_timeout_seconds,
            is_enabled=payload.is_enabled,
        )
        self._validate_payload(normalized)

        try:
            rule = account_repository.create_strategy_rule(
                user_id=current_user.id,
                **normalized,
            )
        except Exception as exc:
            raise AccountPersistenceError("保存规则失败：写入数据库时出错。") from exc

        return StrategyRuleResult(rule=rule)

    def update_rule(
        self,
        rule_id: int,
        payload: StrategyRuleUpdateRequest,
        current_user: AuthUser,
    ) -> StrategyRuleResult:
        existing_rule = account_repository.get_strategy_rule_by_id(rule_id, current_user.id)
        if existing_rule is None:
            raise AccountNotFoundError("规则不存在，或你无权编辑该规则。")

        normalized = self._normalize_payload(
            name=payload.name,
            strategy_type=payload.strategy_type,
            annualized_rate_threshold=payload.annualized_rate_threshold,
            min_net_funding_rate_threshold=payload.min_net_funding_rate_threshold,
            spread_rate_threshold=payload.spread_rate_threshold,
            open_spread_rate_max_threshold=payload.open_spread_rate_max_threshold,
            min_close_spread_rate_threshold=payload.min_close_spread_rate_threshold,
            max_spread_rate_threshold=payload.max_spread_rate_threshold,
            max_pairs=payload.max_pairs,
            order_amount_usdt=payload.order_amount_usdt,
            max_position_usdt=payload.max_position_usdt,
            order_interval_seconds=payload.order_interval_seconds,
            split_order_amount_usdt=payload.split_order_amount_usdt,
            funding_open_window_start_minutes=payload.funding_open_window_start_minutes,
            funding_open_window_end_minutes=payload.funding_open_window_end_minutes,
            funding_settlement_skew_minutes=payload.funding_settlement_skew_minutes,
            funding_spread_resonance_min=payload.funding_spread_resonance_min,
            net_spread_threshold=payload.net_spread_threshold,
            funding_carry_min=payload.funding_carry_min,
            max_funding_cost=payload.max_funding_cost,
            min_net_profit_threshold=payload.min_net_profit_threshold,
            take_profit_threshold=payload.take_profit_threshold,
            drawdown_add_step_percent=payload.drawdown_add_step_percent,
            max_hold_minutes=payload.max_hold_minutes,
            close_interval_seconds=payload.close_interval_seconds,
            close_batch_count=payload.close_batch_count,
            close_batch_ratio_percent=payload.close_batch_ratio_percent,
            single_leg_timeout_seconds=payload.single_leg_timeout_seconds,
            is_enabled=payload.is_enabled,
        )
        self._validate_payload(normalized)

        try:
            rule = account_repository.update_strategy_rule(
                rule_id=rule_id,
                user_id=current_user.id,
                **normalized,
            )
        except Exception as exc:
            raise AccountPersistenceError("更新规则失败：写入数据库时出错。") from exc

        if rule is None:
            raise AccountNotFoundError("规则不存在，或你无权编辑该规则。")

        disabled_now = bool(existing_rule.get("is_enabled")) and not bool(normalized.get("is_enabled"))
        if disabled_now and bool(payload.close_positions_on_disable):
            self._schedule_close_for_rule_open_positions(
                user_id=current_user.id,
                strategy_rule_id=int(rule.id),
            )

        return StrategyRuleResult(rule=rule)

    def delete_rule(self, rule_id: int, current_user: AuthUser) -> None:
        try:
            deleted = account_repository.delete_strategy_rule(rule_id=rule_id, user_id=current_user.id)
        except Exception as exc:
            raise AccountPersistenceError("删除规则失败：数据库操作异常。") from exc

        if not deleted:
            raise AccountNotFoundError("规则不存在，或你无权删除该规则。")

    def build_summary_cards(self, rule_rows: List[Dict[str, object]]) -> List[Dict[str, str]]:
        funding_count = sum(1 for row in rule_rows if str(row.get("strategy_type") or "") == "funding")
        spread_count = sum(1 for row in rule_rows if str(row.get("strategy_type") or "") == "spread")
        enabled_count = sum(1 for row in rule_rows if bool(row.get("is_enabled")))
        disabled_count = sum(1 for row in rule_rows if not bool(row.get("is_enabled")))

        return [
            {
                "key": "rule_count",
                "label": "规则总数",
                "value": str(len(rule_rows)),
                "change": f"资金费 {funding_count} 条 / 价差 {spread_count} 条",
                "tone": "brand",
            },
            {
                "key": "enabled_count",
                "label": "已启用",
                "value": str(enabled_count),
                "change": "会参与自动扫描与开仓",
                "tone": "positive",
            },
            {
                "key": "disabled_count",
                "label": "已停用",
                "value": str(disabled_count),
                "change": "不会继续触发新的开仓",
                "tone": "warning",
            },
            {
                "key": "rule_scope",
                "label": "控制维度",
                "value": "阈值 / 价差 / 仓位",
                "change": "统一控制开平仓阈值、最大价差、最大持仓和下单节奏",
                "tone": "brand",
            },
        ]

    def _normalize_payload(
        self,
        *,
        name: str,
        strategy_type: str,
        annualized_rate_threshold: float,
        min_net_funding_rate_threshold: float,
        spread_rate_threshold: float,
        open_spread_rate_max_threshold: float,
        min_close_spread_rate_threshold: float,
        max_spread_rate_threshold: float,
        max_pairs: int,
        order_amount_usdt: float,
        max_position_usdt: float,
        order_interval_seconds: int,
        split_order_amount_usdt: float,
        funding_open_window_start_minutes: int,
        funding_open_window_end_minutes: int,
        funding_settlement_skew_minutes: int,
        funding_spread_resonance_min: float,
        net_spread_threshold: float,
        funding_carry_min: float,
        max_funding_cost: float,
        min_net_profit_threshold: float,
        take_profit_threshold: float,
        drawdown_add_step_percent: float,
        max_hold_minutes: int,
        close_interval_seconds: int,
        close_batch_count: int,
        close_batch_ratio_percent: float,
        single_leg_timeout_seconds: int,
        is_enabled: bool,
    ) -> Dict[str, object]:
        return {
            "name": str(name or "").strip(),
            "strategy_type": str(strategy_type or "").strip().lower(),
            "annualized_rate_threshold": round(float(annualized_rate_threshold or 0), 4),
            "min_net_funding_rate_threshold": round(float(min_net_funding_rate_threshold or 0), 4),
            "spread_rate_threshold": round(float(spread_rate_threshold or 0), 4),
            "open_spread_rate_max_threshold": round(float(open_spread_rate_max_threshold or 0), 4),
            "min_close_spread_rate_threshold": round(float(min_close_spread_rate_threshold or 0), 4),
            "max_spread_rate_threshold": round(float(max_spread_rate_threshold or 0), 4),
            "max_pairs": int(max_pairs or 0),
            "order_amount_usdt": round(float(order_amount_usdt or 0), 2),
            "max_position_usdt": round(float(max_position_usdt or 0), 2),
            "order_interval_seconds": int(order_interval_seconds or 0),
            "split_order_amount_usdt": round(float(split_order_amount_usdt or 0), 2),
            "funding_open_window_start_minutes": int(funding_open_window_start_minutes or 0),
            "funding_open_window_end_minutes": int(funding_open_window_end_minutes or 0),
            "funding_settlement_skew_minutes": int(funding_settlement_skew_minutes or 0),
            "funding_spread_resonance_min": round(float(funding_spread_resonance_min or 0), 4),
            "net_spread_threshold": round(float(net_spread_threshold or 0), 4),
            "funding_carry_min": round(float(funding_carry_min or 0), 4),
            "max_funding_cost": round(float(max_funding_cost or 0), 4),
            "min_net_profit_threshold": round(float(min_net_profit_threshold or 0), 4),
            "take_profit_threshold": round(float(take_profit_threshold or 0), 4),
            "drawdown_add_step_percent": round(float(drawdown_add_step_percent or 0), 4),
            "max_hold_minutes": int(max_hold_minutes or 0),
            "close_interval_seconds": int(close_interval_seconds or 0),
            "close_batch_count": int(close_batch_count or 0),
            "close_batch_ratio_percent": round(float(close_batch_ratio_percent or 0), 4),
            "single_leg_timeout_seconds": int(single_leg_timeout_seconds or 0),
            "is_enabled": bool(is_enabled),
        }

    def _validate_payload(self, payload: Dict[str, object]) -> None:
        strategy_type = str(payload["strategy_type"])
        if not str(payload["name"]):
            raise AccountValidationError("规则名称不能为空。")
        if strategy_type not in STRATEGY_TYPE_LABELS:
            raise AccountValidationError("规则类型不在支持范围内。")
        if int(payload["max_pairs"]) <= 0:
            raise AccountValidationError("最大开仓交易对数量必须大于 0。")
        if float(payload["order_amount_usdt"]) <= 0:
            raise AccountValidationError("单笔下单金额必须大于 0。")
        if float(payload["max_position_usdt"]) <= 0:
            raise AccountValidationError("最大持仓必须大于 0。")
        if float(payload["split_order_amount_usdt"]) < 0:
            raise AccountValidationError("实际子委托金额不能小于 0。")
        if float(payload["max_spread_rate_threshold"]) <= 0:
            raise AccountValidationError("最大价差阈值必须大于 0。")
        if int(payload["order_interval_seconds"]) < 0:
            raise AccountValidationError("加单间隔时间不能小于 0。")
        integer_field_labels = {
            "funding_open_window_start_minutes": "结算前最早开仓时间",
            "funding_open_window_end_minutes": "结算前停止新开时间",
            "funding_settlement_skew_minutes": "结算时间差",
            "max_hold_minutes": "最大持有时间",
            "close_interval_seconds": "平仓间隔时间",
            "close_batch_count": "平仓批次数",
            "single_leg_timeout_seconds": "单腿异常处理时间",
        }
        for field_name, field_label in integer_field_labels.items():
            if int(payload[field_name]) < 0:
                raise AccountValidationError(f"{field_label}不能小于 0。")
        percent_field_labels = {
            "funding_spread_resonance_min": "最小同向价差",
            "net_spread_threshold": "净价差阈值",
            "funding_carry_min": "资金费 Carry 下限",
            "max_funding_cost": "最大资金费成本",
            "min_net_profit_threshold": "最低净收益保护",
            "take_profit_threshold": "止盈收益阈值",
            "drawdown_add_step_percent": "浮亏加仓阶梯间隔",
            "close_batch_ratio_percent": "单批平仓金额",
        }
        for field_name, field_label in percent_field_labels.items():
            if float(payload[field_name]) < 0:
                raise AccountValidationError(f"{field_label}不能小于 0。")
        funding_window_start = int(payload["funding_open_window_start_minutes"])
        funding_window_end = int(payload["funding_open_window_end_minutes"])
        if funding_window_start > 0 and funding_window_end > 0 and funding_window_start < funding_window_end:
            raise AccountValidationError("结算前最早开仓时间不能小于停止新开时间。")
        if strategy_type == "funding" and float(payload["annualized_rate_threshold"]) <= 0:
            raise AccountValidationError("资金费套利规则的净资金费率必须大于 0。")
        if strategy_type == "funding" and float(payload["min_net_funding_rate_threshold"]) <= 0:
            raise AccountValidationError("资金费套利规则的最小净资金费率必须大于 0。")
        if strategy_type == "funding" and float(payload["min_net_funding_rate_threshold"]) > float(payload["annualized_rate_threshold"]):
            raise AccountValidationError("最小净资金费率不能大于净资金费率。")
        if strategy_type == "spread" and float(payload["spread_rate_threshold"]) <= 0:
            raise AccountValidationError("价差套利规则的价差率阈值必须大于 0。")
        if (
            strategy_type == "spread"
            and float(payload["open_spread_rate_max_threshold"]) > 0
            and float(payload["open_spread_rate_max_threshold"]) < float(payload["spread_rate_threshold"])
        ):
            raise AccountValidationError("开仓最大价差率不能小于开仓最小价差率。")
        if strategy_type == "spread" and float(payload["min_close_spread_rate_threshold"]) <= 0:
            raise AccountValidationError("价差套利规则的最小平仓价差阈值必须大于 0。")
        if strategy_type == "spread" and float(payload["min_close_spread_rate_threshold"]) > float(payload["spread_rate_threshold"]):
            raise AccountValidationError("最小平仓价差阈值不能大于开仓价差率阈值。")
        if (
            strategy_type == "spread"
            and float(payload["split_order_amount_usdt"]) > 0
            and float(payload["split_order_amount_usdt"]) > float(payload["order_amount_usdt"])
        ):
            raise AccountValidationError("实际子委托金额不能大于每次开仓/加仓目标金额。")

    def _build_rule_row(self, row: Dict[str, object]) -> Dict[str, object]:
        strategy_type = str(row.get("strategy_type") or "")
        runtime_rule = strategy_rule_runtime_service.build_runtime_view(row)
        funding_open_threshold = float(row.get("annualized_rate_threshold") or 0)
        min_net_funding_rate_threshold = float(row.get("min_net_funding_rate_threshold") or 0)
        spread_threshold = float(row.get("spread_rate_threshold") or 0)
        open_spread_rate_max_threshold = float(row.get("open_spread_rate_max_threshold") or 0)
        min_close_spread_rate_threshold = float(row.get("min_close_spread_rate_threshold") or 0)
        max_spread_rate_threshold = runtime_rule.stop_loss_price_diff
        is_enabled = bool(row.get("is_enabled"))
        order_amount_usdt = float(row.get("order_amount_usdt") or 0)
        max_position_usdt = runtime_rule.max_position_usdt
        split_order_amount_usdt = float(row.get("split_order_amount_usdt") or 0)

        active_position_amount = 0.0
        user_id = int(row.get("user_id") or 0)
        rule_id = int(row.get("id") or 0)
        if user_id > 0 and rule_id > 0:
            active_position_amount = arbitrage_execution_repository.sum_committed_position_amount_by_rule(
                user_id=user_id,
                strategy_rule_id=rule_id,
            )

        if strategy_type == "funding":
            trigger_text = (
                f"开仓净资金费率 > {funding_open_threshold:.4f}% / "
                f"平仓净资金费率 < {min_net_funding_rate_threshold:.4f}% / "
                f"最大价差 <= {max_spread_rate_threshold:.6f}"
            )
            min_close_threshold_text = f"{min_net_funding_rate_threshold:.4f}%"
        else:
            trigger_text = (
                f"开仓 >= {spread_threshold:.2f}% / "
                f"平仓 <= {min_close_spread_rate_threshold:.2f}% / "
                f"最大价差 <= {max_spread_rate_threshold:.6f}"
            )
            min_close_threshold_text = f"{min_close_spread_rate_threshold:.2f}%"

        return {
            "id": rule_id,
            "name": str(row.get("name") or "--"),
            "strategy_type": strategy_type,
            "strategy_type_label": STRATEGY_TYPE_LABELS.get(strategy_type, strategy_type),
            "annualized_rate_threshold": funding_open_threshold,
            "min_net_funding_rate_threshold": min_net_funding_rate_threshold,
            "min_net_funding_rate_threshold_text": f"{min_net_funding_rate_threshold:.4f}%",
            "spread_rate_threshold": spread_threshold,
            "open_spread_rate_max_threshold": open_spread_rate_max_threshold,
            "min_close_spread_rate_threshold": min_close_spread_rate_threshold,
            "min_close_spread_rate_threshold_text": f"{min_close_spread_rate_threshold:.2f}%",
            "min_close_threshold_text": min_close_threshold_text,
            "max_spread_rate_threshold": max_spread_rate_threshold,
            "max_spread_rate_threshold_text": self._format_quantity_value(max_spread_rate_threshold),
            "trigger_text": trigger_text,
            "max_pairs": int(row.get("max_pairs") or 0),
            "order_amount_usdt": order_amount_usdt,
            "order_amount_text": self._format_money(order_amount_usdt),
            "max_position_usdt": max_position_usdt,
            "max_position_text": self._format_money(max_position_usdt),
            "order_interval_seconds": int(row.get("order_interval_seconds") or 0),
            "order_interval_text": f"{int(row.get('order_interval_seconds') or 0)} 秒",
            "split_order_amount_usdt": split_order_amount_usdt,
            "funding_open_window_start_minutes": int(row.get("funding_open_window_start_minutes") or 0),
            "funding_open_window_end_minutes": int(row.get("funding_open_window_end_minutes") or 0),
            "funding_settlement_skew_minutes": int(row.get("funding_settlement_skew_minutes") or 0),
            "funding_spread_resonance_min": float(row.get("funding_spread_resonance_min") or 0),
            "net_spread_threshold": float(row.get("net_spread_threshold") or 0),
            "funding_carry_min": float(row.get("funding_carry_min") or 0),
            "max_funding_cost": float(row.get("max_funding_cost") or 0),
            "min_net_profit_threshold": float(row.get("min_net_profit_threshold") or 0),
            "take_profit_threshold": float(row.get("take_profit_threshold") or 0),
            "drawdown_add_step_percent": float(row.get("drawdown_add_step_percent") or 0),
            "max_hold_minutes": int(row.get("max_hold_minutes") or 0),
            "close_interval_seconds": int(row.get("close_interval_seconds") or 0),
            "close_batch_count": int(row.get("close_batch_count") or 0),
            "close_batch_ratio_percent": float(row.get("close_batch_ratio_percent") or 0),
            "single_leg_timeout_seconds": int(row.get("single_leg_timeout_seconds") or 0),
            "is_enabled": is_enabled,
            "status_label": "已启用" if is_enabled else "已停用",
            "status_tone": "positive" if is_enabled else "warning",
            "updated_at": self._format_datetime(row.get("updated_at")),
            "active_position_amount_usdt": float(active_position_amount or 0),
            "active_position_quantity": float(active_position_amount or 0),
        }

    def _schedule_close_for_rule_open_positions(self, *, user_id: int, strategy_rule_id: int) -> None:
        executions = arbitrage_execution_repository.list_active_open_executions_for_user(
            user_id=user_id,
            limit=500,
        )
        for execution_row in executions:
            if int(execution_row.get("strategy_rule_id") or 0) != strategy_rule_id:
                continue
            if str(execution_row.get("action") or "").strip().lower() != "open":
                continue
            if str(execution_row.get("status") or "").strip().lower() not in {"opening", "open"}:
                continue
            pair_key = str(execution_row.get("pair_key") or "")
            if arbitrage_execution_repository.has_open_close_execution(
                user_id=user_id,
                strategy_rule_id=strategy_rule_id,
                pair_key=pair_key,
            ):
                continue
            result = arbitrage_execution_plan_service.create_close_execution(
                execution_row=execution_row,
                reason="规则已停用，按用户操作发起全部平仓",
            )
            if result is None:
                continue
            arbitrage_execution_repository.update_execution_status(
                execution_id=int(execution_row.get("id") or 0),
                status="closing",
            )

    def _format_money(self, value: float) -> str:
        return f"${value:,.2f}".rstrip("0").rstrip(".")

    def _format_quantity_value(self, value: float) -> str:
        numeric = float(value or 0)
        if numeric >= 1000:
            return f"{numeric:,.0f}".rstrip("0").rstrip(".")
        if numeric >= 1:
            return f"{numeric:,.4f}".rstrip("0").rstrip(".")
        return f"{numeric:,.8f}".rstrip("0").rstrip(".")

    def _format_datetime(self, value) -> str:
        if value is None:
            return "--"
        return value.strftime("%Y-%m-%d %H:%M")


strategy_rule_service = StrategyRuleService()
