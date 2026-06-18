"""Dashboard summary service backed by real runtime data."""

from __future__ import annotations

from typing import Dict, List

from app.domain.entities import AuthUser
from app.infrastructure.cache import market_runtime_cache

from .account_service import account_service
from .local_position_service import local_position_service
from .monitor_center_service import monitor_center_service
from .opportunity_exchange_filter_service import opportunity_exchange_filter_service


class DashboardService:
    def build_payload_for_user(self, current_user: AuthUser) -> Dict[str, object]:
        account_rows = account_service.build_account_rows_for_user(current_user.id)
        auto_transfer_config = account_service.get_auto_transfer_config(current_user.id)
        balance_rows = account_service.build_balance_rows_from_accounts(
            account_rows,
            auto_transfer_config.trigger_ratio,
        )
        funding_rows = local_position_service.enrich_opportunity_rows(
            rows=opportunity_exchange_filter_service.filter_rows(
                market_runtime_cache.get_user_rows("funding", current_user.id)
            )
        )
        spread_rows = local_position_service.enrich_opportunity_rows(
            rows=opportunity_exchange_filter_service.filter_rows(
                market_runtime_cache.get_user_rows("spread", current_user.id)
            )
        )
        workers = monitor_center_service.snapshot()

        summary_cards = self._build_summary_cards(
            account_rows=account_rows,
            balance_rows=balance_rows,
            funding_rows=funding_rows,
            spread_rows=spread_rows,
            workers=workers,
        )
        dashboard_rows = self._build_dashboard_rows(funding_rows, spread_rows)

        return {
            "success": True,
            "message": "dashboard loaded",
            "summary_cards": summary_cards,
            "dashboard_rows": dashboard_rows,
            "dashboard_count": len(dashboard_rows),
        }

    def _build_summary_cards(
        self,
        *,
        account_rows: List[Dict[str, str]],
        balance_rows: List[Dict[str, str]],
        funding_rows: List[dict],
        spread_rows: List[dict],
        workers: List[dict],
    ) -> List[Dict[str, str]]:
        total_available = sum(self._parse_amount(str(row.get("available") or "$0")) for row in balance_rows)
        success_accounts = sum(
            1
            for row in account_rows
            if str(row.get("connection_test_status_tone") or "").strip().lower() == "positive"
        )
        running_workers = sum(1 for item in workers if str(item.get("status") or "") == "running")
        error_workers = sum(1 for item in workers if str(item.get("status") or "") == "error")
        opportunity_count = len(funding_rows) + len(spread_rows)

        return [
            {
                "key": "total_available",
                "label": "总可用资金",
                "value": self._format_amount(total_available),
                "change": f"已汇总 {len(account_rows)} 个账户的当前可用余额",
                "tone": "positive",
            },
            {
                "key": "opportunity_count",
                "label": "可执行机会",
                "value": str(opportunity_count),
                "change": f"资金费 {len(funding_rows)} / 价差 {len(spread_rows)}",
                "tone": "brand",
            },
            {
                "key": "connected_accounts",
                "label": "已通过连接测试",
                "value": f"{success_accounts} / {len(account_rows)}",
                "change": "仅统计连接测试成功的账户",
                "tone": "neutral",
            },
            {
                "key": "worker_status",
                "label": "后台线程状态",
                "value": f"{running_workers} 运行中",
                "change": f"异常 {error_workers} 个",
                "tone": "warning" if error_workers else "positive",
            },
        ]

    def _build_dashboard_rows(self, funding_rows: List[dict], spread_rows: List[dict]) -> List[Dict[str, str]]:
        funding_items = [
            {
                "rank_sort": self._percent_to_number(str(row.get("annual") or "0")),
                "type": "资金费套利",
                "type_tone": "brand",
                "symbol": str(row.get("symbol") or "--"),
                "line_a": f"做多 {row.get('symbol', '--')}/USDT / {row.get('long_exchange', '--')}",
                "line_a_tone": "positive",
                "line_b": f"做空 {row.get('symbol', '--')}/USDT / {row.get('short_exchange', '--')}",
                "line_b_tone": "negative",
                "yield_label": "当前年化",
                "yield_value": str(row.get("annual") or "--"),
                "metric_label": "净资金费率",
                "metric_value": str(row.get("net_rate") or "--"),
                "edge_label": "价差率",
                "edge_value": str(row.get("spread") or "--"),
                "edge_tone": "positive" if "+" in str(row.get("spread") or "") else "negative",
                "qty_long": f"{row.get('long_exchange', '--')} {row.get('qty_long', '--')}",
                "qty_short": f"{row.get('short_exchange', '--')} {row.get('qty_short', '--')}",
                "avg_long": f"{row.get('long_exchange', '--')} {row.get('avg_long', '--')}",
                "avg_short": f"{row.get('short_exchange', '--')} {row.get('avg_short', '--')}",
                "value_long": f"{row.get('long_exchange', '--')} {row.get('value_long', '--')}",
                "value_short": f"{row.get('short_exchange', '--')} {row.get('value_short', '--')}",
                "highlight_label": "距离结算",
                "highlight_value": str(row.get("settlement") or "--"),
            }
            for row in funding_rows[:5]
        ]

        spread_items = [
            {
                "rank_sort": self._percent_to_number(str(row.get("net_spread") or "0")),
                "type": "价差套利",
                "type_tone": "positive",
                "symbol": str(row.get("symbol") or "--"),
                "line_a": f"买入 {row.get('symbol', '--')}/USDT / {row.get('buy_exchange', '--')}",
                "line_a_tone": "positive",
                "line_b": f"卖出 {row.get('symbol', '--')}/USDT / {row.get('sell_exchange', '--')}",
                "line_b_tone": "negative",
                "yield_label": "最新价差",
                "yield_value": str(row.get("latest_spread") or "--"),
                "metric_label": "净价差",
                "metric_value": str(row.get("net_spread") or "--"),
                "edge_label": "手续费",
                "edge_value": f"{row.get('buy_fee_rate', '--')} / {row.get('sell_fee_rate', '--')}",
                "edge_tone": "",
                "qty_long": f"{row.get('buy_exchange', '--')} {row.get('qty_long', '--')}",
                "qty_short": f"{row.get('sell_exchange', '--')} {row.get('qty_short', '--')}",
                "avg_long": f"{row.get('buy_exchange', '--')} {row.get('avg_long', '--')}",
                "avg_short": f"{row.get('sell_exchange', '--')} {row.get('avg_short', '--')}",
                "value_long": f"{row.get('buy_exchange', '--')} {row.get('value_long', '--')}",
                "value_short": f"{row.get('sell_exchange', '--')} {row.get('value_short', '--')}",
                "highlight_label": "机会时间",
                "highlight_value": str(row.get("opportunity_time") or "--"),
            }
            for row in spread_rows[:5]
        ]

        rows = sorted(funding_items + spread_items, key=lambda item: item["rank_sort"], reverse=True)[:5]
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
            row.pop("rank_sort", None)
        return rows

    def _percent_to_number(self, value: str) -> float:
        normalized = str(value or "").replace("%", "").replace("+", "").replace(",", "").strip()
        try:
            return float(normalized)
        except ValueError:
            return 0.0

    def _parse_amount(self, value: str) -> float:
        normalized = str(value or "").replace("$", "").replace(",", "").strip()
        try:
            return float(normalized)
        except ValueError:
            return 0.0

    def _format_amount(self, value: float) -> str:
        return f"${value:,.0f}"


dashboard_service = DashboardService()
