"""Strategy rule service for rule management page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from app.application.dto.requests.strategy_requests import (
    StrategyRuleCreateRequest,
    StrategyRuleUpdateRequest,
)
from app.domain.entities import AuthUser, StrategyRule
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
            spread_rate_threshold=payload.spread_rate_threshold,
            max_spread_rate_threshold=payload.max_spread_rate_threshold,
            max_pairs=payload.max_pairs,
            order_amount_usdt=payload.order_amount_usdt,
            max_position_usdt=payload.max_position_usdt,
            order_interval_seconds=payload.order_interval_seconds,
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
        normalized = self._normalize_payload(
            name=payload.name,
            strategy_type=payload.strategy_type,
            annualized_rate_threshold=payload.annualized_rate_threshold,
            spread_rate_threshold=payload.spread_rate_threshold,
            max_spread_rate_threshold=payload.max_spread_rate_threshold,
            max_pairs=payload.max_pairs,
            order_amount_usdt=payload.order_amount_usdt,
            max_position_usdt=payload.max_position_usdt,
            order_interval_seconds=payload.order_interval_seconds,
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
                "change": "不会继续触发新开仓",
                "tone": "warning",
            },
            {
                "key": "rule_scope",
                "label": "控制维度",
                "value": "阈值 / 价差 / 仓位",
                "change": "统一控制触发阈值、最大价差、最大持仓和下单节奏",
                "tone": "brand",
            },
        ]

    def _normalize_payload(
        self,
        *,
        name: str,
        strategy_type: str,
        annualized_rate_threshold: float,
        spread_rate_threshold: float,
        max_spread_rate_threshold: float,
        max_pairs: int,
        order_amount_usdt: float,
        max_position_usdt: float,
        order_interval_seconds: int,
        is_enabled: bool,
    ) -> Dict[str, object]:
        return {
            "name": str(name or "").strip(),
            "strategy_type": str(strategy_type or "").strip().lower(),
            "annualized_rate_threshold": round(float(annualized_rate_threshold or 0), 4),
            "spread_rate_threshold": round(float(spread_rate_threshold or 0), 4),
            "max_spread_rate_threshold": round(float(max_spread_rate_threshold or 0), 4),
            "max_pairs": int(max_pairs or 0),
            "order_amount_usdt": round(float(order_amount_usdt or 0), 2),
            "max_position_usdt": round(float(max_position_usdt or 0), 2),
            "order_interval_seconds": int(order_interval_seconds or 0),
            "is_enabled": bool(is_enabled),
        }

    def _validate_payload(self, payload: Dict[str, object]) -> None:
        strategy_type = str(payload["strategy_type"])
        if not str(payload["name"]):
            raise AccountValidationError("规则名称不能为空。")
        if strategy_type not in STRATEGY_TYPE_LABELS:
            raise AccountValidationError("规则类型不在支持范围内。")
        if int(payload["max_pairs"]) <= 0:
            raise AccountValidationError("最大开仓交易对数必须大于 0。")
        if float(payload["order_amount_usdt"]) <= 0:
            raise AccountValidationError("单笔下单金额必须大于 0。")
        if float(payload["max_position_usdt"]) <= 0:
            raise AccountValidationError("最大持仓必须大于 0。")
        if float(payload["max_position_usdt"]) < float(payload["order_amount_usdt"]):
            raise AccountValidationError("最大持仓不能小于单笔下单金额。")
        if float(payload["max_spread_rate_threshold"]) <= 0:
            raise AccountValidationError("最大价差阈值必须大于 0。")
        if strategy_type == "spread" and float(payload["max_spread_rate_threshold"]) < float(payload["spread_rate_threshold"]):
            raise AccountValidationError("最大价差阈值不能小于价差率阈值。")
        if int(payload["order_interval_seconds"]) < 0:
            raise AccountValidationError("下单间隔时间不能小于 0。")
        if strategy_type == "funding" and float(payload["annualized_rate_threshold"]) <= 0:
            raise AccountValidationError("资金费套利规则的年化阈值必须大于 0。")
        if strategy_type == "spread" and float(payload["spread_rate_threshold"]) <= 0:
            raise AccountValidationError("价差套利规则的价差率阈值必须大于 0。")

    def _build_rule_row(self, row: Dict[str, object]) -> Dict[str, object]:
        strategy_type = str(row.get("strategy_type") or "")
        annualized_threshold = float(row.get("annualized_rate_threshold") or 0)
        spread_threshold = float(row.get("spread_rate_threshold") or 0)
        max_spread_rate_threshold = float(row.get("max_spread_rate_threshold") or 0)
        is_enabled = bool(row.get("is_enabled"))
        order_amount_usdt = float(row.get("order_amount_usdt") or 0)
        max_position_usdt = float(row.get("max_position_usdt") or 0)
        if max_position_usdt <= 0:
            max_position_usdt = order_amount_usdt

        trigger_text = (
            f"年化 >= {annualized_threshold:.2f}% / 价差 <= {max_spread_rate_threshold:.2f}%"
            if strategy_type == "funding"
            else f"价差 >= {spread_threshold:.2f}% / 价差 <= {max_spread_rate_threshold:.2f}%"
        )

        return {
            "id": int(row["id"]),
            "name": str(row.get("name") or "--"),
            "strategy_type": strategy_type,
            "strategy_type_label": STRATEGY_TYPE_LABELS.get(strategy_type, strategy_type),
            "annualized_rate_threshold": annualized_threshold,
            "spread_rate_threshold": spread_threshold,
            "max_spread_rate_threshold": max_spread_rate_threshold,
            "max_spread_rate_threshold_text": f"{max_spread_rate_threshold:.2f}%",
            "trigger_text": trigger_text,
            "max_pairs": int(row.get("max_pairs") or 0),
            "order_amount_usdt": order_amount_usdt,
            "order_amount_text": self._format_money(order_amount_usdt),
            "max_position_usdt": max_position_usdt,
            "max_position_text": self._format_money(max_position_usdt),
            "order_interval_seconds": int(row.get("order_interval_seconds") or 0),
            "order_interval_text": f"{int(row.get('order_interval_seconds') or 0)} 秒",
            "is_enabled": is_enabled,
            "status_label": "已启用" if is_enabled else "已停用",
            "status_tone": "positive" if is_enabled else "warning",
            "updated_at": self._format_datetime(row.get("updated_at")),
        }

    def _format_money(self, value: float) -> str:
        return f"${value:,.2f}".rstrip("0").rstrip(".")

    def _format_datetime(self, value) -> str:
        if value is None:
            return "--"
        return value.strftime("%Y-%m-%d %H:%M")


strategy_rule_service = StrategyRuleService()
