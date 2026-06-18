"""Navigation view model definitions."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.domain.entities import AuthUser
from app.views.viewmodels.page_models import NavItem


APP_NAME = "ArbiMatrix"

NAV_ITEMS: Tuple[NavItem, ...] = (
    NavItem(key="dashboard", label="首页", href="/dashboard"),
    NavItem(key="funding_arbitrage", label="资金费套利", href="/funding-arbitrage"),
    NavItem(key="spread_arbitrage", label="价差套利", href="/spread-arbitrage"),
    NavItem(key="strategy_list", label="规则管理", href="/strategies"),
    NavItem(key="positions_orders", label="运行监控", href="/positions-orders"),
    NavItem(key="accounts", label="账户调度", href="/accounts"),
    NavItem(key="risk_alerts", label="线程监控", href="/risk-alerts"),
    NavItem(key="redis_inspector", label="Redis", href="/redis-inspector"),
    NavItem(key="system_settings", label="系统配置", href="/system-settings"),
)


def build_nav_items(current_user: Optional[AuthUser] = None) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    is_admin = bool(current_user and current_user.is_admin)

    for item in NAV_ITEMS:
        if item.key in {"system_settings", "redis_inspector"} and not is_admin:
            continue
        items.append(item.to_dict())

    return items
