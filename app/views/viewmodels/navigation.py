"""Navigation view model definitions."""

from typing import Dict, List, Tuple

from app.views.viewmodels.page_models import NavItem


APP_NAME = "ArbiMatrix"

NAV_ITEMS: Tuple[NavItem, ...] = (
    NavItem(key="dashboard", label="首页", href="/dashboard"),
    NavItem(key="funding_arbitrage", label="资金费套利", href="/funding-arbitrage"),
    NavItem(key="spread_arbitrage", label="价差套利", href="/spread-arbitrage"),
    NavItem(key="strategy_list", label="规则管理", href="/strategies"),
    NavItem(key="positions_orders", label="持仓订单", href="/positions-orders"),
    NavItem(key="accounts", label="账户调度", href="/accounts"),
    NavItem(key="risk_alerts", label="风控告警", href="/risk-alerts"),
)


def build_nav_items() -> List[Dict[str, str]]:
    return [item.to_dict() for item in NAV_ITEMS]
