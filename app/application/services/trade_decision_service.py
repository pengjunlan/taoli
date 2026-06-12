"""Runtime strategy decision service backed by real opportunity rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


class TradeDecisionService:
    def build_runtime_payload(
        self,
        *,
        user_id: int,
        account_rows: List[Dict[str, Any]],
        strategy_rows: List[Dict[str, Any]],
        funding_rows: List[Dict[str, Any]],
        spread_rows: List[Dict[str, Any]],
    ) -> Dict[str, object]:
        enabled_rules = [row for row in strategy_rows if bool(row.get("is_enabled"))]
        funding_rules = [row for row in enabled_rules if str(row.get("strategy_type") or "") == "funding"]
        spread_rules = [row for row in enabled_rules if str(row.get("strategy_type") or "") == "spread"]

        candidates: List[Dict[str, object]] = []
        candidates.extend(self._build_funding_candidates(funding_rows, funding_rules))
        candidates.extend(self._build_spread_candidates(spread_rows, spread_rules))

        positions_rows = self._build_position_rows(candidates)
        order_rows = self._build_order_rows(candidates)
        fill_rows = self._build_fill_rows()
        summary_cards = self._build_summary_cards(candidates, positions_rows, order_rows, fill_rows)

        return {
            "user_id": user_id,
            "generated_at": datetime.now(),
            "enabled_rule_count": len(enabled_rules),
            "account_count": len(account_rows),
            "candidate_rows": candidates,
            "positions_rows": positions_rows,
            "order_rows": order_rows,
            "fill_rows": fill_rows,
            "summary_cards": summary_cards,
        }

    def _build_funding_candidates(
        self,
        opportunity_rows: List[Dict[str, Any]],
        rule_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, object]]:
        if not opportunity_rows or not rule_rows:
            return []

        default_rule = rule_rows[0]
        result: List[Dict[str, object]] = []
        for rank, row in enumerate(opportunity_rows, start=1):
            annualized = self._parse_percent(row.get("annual"))
            net_rate = self._parse_percent(row.get("net_rate"))
            spread = abs(self._parse_percent(row.get("spread")))
            matched_rule = next(
                (
                    rule
                    for rule in rule_rows
                    if annualized >= float(rule.get("annualized_rate_threshold") or 0)
                    and (
                        float(rule.get("max_spread_rate_threshold") or 0) <= 0
                        or spread <= float(rule.get("max_spread_rate_threshold") or 0)
                    )
                ),
                None,
            )
            if matched_rule is None:
                continue

            order_amount = float(matched_rule.get("order_amount_usdt") or 0)
            max_position = float(matched_rule.get("max_position_usdt") or order_amount)
            result.append(
                {
                    "rank": rank,
                    "strategy_type": "funding",
                    "strategy_label": "资金费套利",
                    "rule_id": int(matched_rule.get("id") or 0),
                    "rule_name": str(matched_rule.get("name") or default_rule.get("name") or "资金费套利规则"),
                    "symbol": str(row.get("symbol") or "--"),
                    "open_exchange": str(row.get("long_exchange") or "--"),
                    "hedge_exchange": str(row.get("short_exchange") or "--"),
                    "primary_metric": str(row.get("annual") or "--"),
                    "secondary_metric": str(row.get("net_rate") or "--"),
                    "risk_metric": str(row.get("spread") or "--"),
                    "planned_order_amount": order_amount,
                    "max_position_usdt": max_position,
                    "order_interval_seconds": int(matched_rule.get("order_interval_seconds") or 0),
                    "reason": (
                        f"命中规则 {matched_rule.get('name') or '--'}："
                        f"年化 {row.get('annual') or '--'}，净资金费率 {row.get('net_rate') or '--'}，"
                        f"价差 {row.get('spread') or '--'}"
                    ),
                    "status": "candidate",
                    "status_label": "待执行评估",
                    "status_tone": "brand",
                    "action_label": "开资金费对冲",
                    "opportunity_time": str(row.get("settlement") or "--"),
                    "position_size_text": self._format_money(min(order_amount, max_position)),
                }
            )
        return result

    def _build_spread_candidates(
        self,
        opportunity_rows: List[Dict[str, Any]],
        rule_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, object]]:
        if not opportunity_rows or not rule_rows:
            return []

        default_rule = rule_rows[0]
        result: List[Dict[str, object]] = []
        for rank, row in enumerate(opportunity_rows, start=1):
            latest_spread = self._parse_percent(row.get("latest_spread"))
            net_spread = self._parse_percent(row.get("net_spread"))
            matched_rule = next(
                (
                    rule
                    for rule in rule_rows
                    if latest_spread >= float(rule.get("spread_rate_threshold") or 0)
                    and (
                        float(rule.get("max_spread_rate_threshold") or 0) <= 0
                        or latest_spread <= float(rule.get("max_spread_rate_threshold") or 0)
                    )
                ),
                None,
            )
            if matched_rule is None:
                continue

            order_amount = float(matched_rule.get("order_amount_usdt") or 0)
            max_position = float(matched_rule.get("max_position_usdt") or order_amount)
            result.append(
                {
                    "rank": rank,
                    "strategy_type": "spread",
                    "strategy_label": "价差套利",
                    "rule_id": int(matched_rule.get("id") or 0),
                    "rule_name": str(matched_rule.get("name") or default_rule.get("name") or "价差套利规则"),
                    "symbol": str(row.get("symbol") or "--"),
                    "open_exchange": str(row.get("buy_exchange") or "--"),
                    "hedge_exchange": str(row.get("sell_exchange") or "--"),
                    "primary_metric": str(row.get("latest_spread") or "--"),
                    "secondary_metric": str(row.get("net_spread") or "--"),
                    "risk_metric": (
                        f"{row.get('buy_fee_rate') or '--'} / {row.get('sell_fee_rate') or '--'}"
                    ),
                    "planned_order_amount": order_amount,
                    "max_position_usdt": max_position,
                    "order_interval_seconds": int(matched_rule.get("order_interval_seconds") or 0),
                    "reason": (
                        f"命中规则 {matched_rule.get('name') or '--'}："
                        f"最新价差 {row.get('latest_spread') or '--'}，净价差 {row.get('net_spread') or '--'}"
                    ),
                    "status": "candidate",
                    "status_label": "待执行评估",
                    "status_tone": "brand",
                    "action_label": "开价差对冲",
                    "opportunity_time": str(row.get("opportunity_time") or "--"),
                    "position_size_text": self._format_money(min(order_amount, max_position)),
                }
            )
        return result

    def _build_position_rows(self, candidates: List[Dict[str, object]]) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for candidate in candidates[:10]:
            rows.append(
                {
                    "symbol": f"{candidate['symbol']}USDT",
                    "strategy": str(candidate["rule_name"]),
                    "long_exchange": str(candidate["open_exchange"]),
                    "short_exchange": str(candidate["hedge_exchange"]),
                    "size": str(candidate["position_size_text"]),
                    "hedge": "候选对冲",
                    "pnl": "--",
                    "status": str(candidate["status_label"]),
                    "reason": str(candidate["reason"]),
                }
            )
        return rows

    def _build_order_rows(self, candidates: List[Dict[str, object]]) -> List[Dict[str, str]]:
        now_text = datetime.now().strftime("%H:%M:%S")
        rows: List[Dict[str, str]] = []
        for candidate in candidates[:20]:
            rows.append(
                {
                    "time": now_text,
                    "symbol": f"{candidate['symbol']}USDT",
                    "exchange": str(candidate["open_exchange"]),
                    "side": str(candidate["action_label"]),
                    "status": str(candidate["status_label"]),
                    "size": str(candidate["position_size_text"]),
                    "strategy": str(candidate["rule_name"]),
                    "reason": str(candidate["reason"]),
                    "status_tone": str(candidate["status_tone"]),
                }
            )
        return rows

    def _build_fill_rows(self) -> List[Dict[str, str]]:
        return []

    def _build_summary_cards(
        self,
        candidates: List[Dict[str, object]],
        positions_rows: List[Dict[str, str]],
        order_rows: List[Dict[str, str]],
        fill_rows: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        funding_count = sum(1 for item in candidates if str(item.get("strategy_type") or "") == "funding")
        spread_count = sum(1 for item in candidates if str(item.get("strategy_type") or "") == "spread")
        total_planned_amount = sum(float(item.get("planned_order_amount") or 0) for item in candidates)

        return [
            {
                "key": "candidate_count",
                "label": "规则命中候选",
                "value": str(len(candidates)),
                "change": f"资金费 {funding_count} / 价差 {spread_count}",
                "tone": "brand",
            },
            {
                "key": "pending_orders",
                "label": "待执行记录",
                "value": str(len(order_rows)),
                "change": "当前仅生成真实运行候选，不直接下单",
                "tone": "warning" if order_rows else "neutral",
            },
            {
                "key": "planned_amount",
                "label": "计划下单资金",
                "value": self._format_money(total_planned_amount),
                "change": "由规则单笔金额汇总得到",
                "tone": "positive" if total_planned_amount > 0 else "neutral",
            },
            {
                "key": "fill_count",
                "label": "真实成交回报",
                "value": str(len(fill_rows)),
                "change": "当前执行引擎未接交易所下单回报",
                "tone": "neutral",
            },
        ]

    def _parse_percent(self, value: object) -> float:
        text = str(value or "").replace("%", "").replace("+", "").replace(",", "").strip()
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _format_money(self, value: float) -> str:
        return f"${float(value or 0):,.2f}".rstrip("0").rstrip(".")


trade_decision_service = TradeDecisionService()

__all__ = [
    "TradeDecisionService",
    "trade_decision_service",
]
