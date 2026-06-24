"""Business services used by controllers and use cases."""

from __future__ import annotations

from importlib import import_module

from app.application.services import registry as _registry
from app.application.services.registry import __all__ as _registry_exports


_MODULE_EXPORT_MAP = {
    "TradeDecisionService": "app.application.services.trade_decision_service",
    "trade_decision_service": "app.application.services.trade_decision_service",
    "MarketDataMonitorService": "app.application.services.market_data_monitor_service",
    "market_data_monitor_service": "app.application.services.market_data_monitor_service",
    "AccountMonitorService": "app.application.services.account_monitor_service",
    "account_monitor_service": "app.application.services.account_monitor_service",
}

__all__ = [
    *_registry_exports,
    "TradeDecisionService",
    "trade_decision_service",
    "MarketDataMonitorService",
    "market_data_monitor_service",
    "AccountMonitorService",
    "account_monitor_service",
]


# Re-export registry symbols eagerly so names like `auth_service` resolve to
# the service singleton instead of the same-named submodule.
for _name in _registry_exports:
    globals()[_name] = getattr(_registry, _name)


def __getattr__(name: str):
    if name in _registry_exports:
        return getattr(_registry, name)

    module_name = _MODULE_EXPORT_MAP.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    return getattr(module, name)
