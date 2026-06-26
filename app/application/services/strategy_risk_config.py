"""Central runtime defaults for strategy risk controls."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class StrategyRiskConfig:
    opportunity_monitor_interval_seconds: int = _env_int("ARBITRAGE_OPPORTUNITY_MONITOR_INTERVAL_SECONDS", 5)
    position_monitor_interval_seconds: int = _env_int("ARBITRAGE_POSITION_MONITOR_INTERVAL_SECONDS", 5)
    order_retry_seconds: int = _env_int("ARBITRAGE_ORDER_RETRY_SECONDS", 5)
    max_order_retries: int = _env_int("ARBITRAGE_MAX_ORDER_RETRIES", 10)
    single_leg_timeout_seconds: int = _env_int("ARBITRAGE_SINGLE_LEG_TIMEOUT_SECONDS", 10)
    failed_open_cooldown_seconds: int = _env_int("ARBITRAGE_FAILED_OPEN_COOLDOWN_SECONDS", 3600)
    max_price_drift_percent: float = _env_float("ARBITRAGE_MAX_PRICE_DRIFT_PERCENT", 0.20)
    pair_balance_tolerance_ratio: float = _env_float("ARBITRAGE_PAIR_BALANCE_TOLERANCE_RATIO", 0.02)
    overlay_available_cap_usdt: float = _env_float("ARBITRAGE_OVERLAY_AVAILABLE_CAP_USDT", 1000.0)
    max_bid_ask_spread_percent: float = _env_float("ARBITRAGE_MAX_BID_ASK_SPREAD_PERCENT", 0.30)
    max_order_book_slippage_percent: float = _env_float("ARBITRAGE_MAX_ORDER_BOOK_SLIPPAGE_PERCENT", 0.30)
    order_book_depth_limit: int = _env_int("ARBITRAGE_ORDER_BOOK_DEPTH_LIMIT", 20)
    min_quote_volume_multiplier: float = _env_float("ARBITRAGE_MIN_QUOTE_VOLUME_MULTIPLIER", 20.0)
    max_funding_settlement_skew_minutes: int = _env_int("ARBITRAGE_MAX_FUNDING_SETTLEMENT_SKEW_MINUTES", 5)
    funding_receipt_confirm_grace_seconds: int = _env_int("ARBITRAGE_FUNDING_RECEIPT_CONFIRM_GRACE_SECONDS", 180)


strategy_risk_config = StrategyRiskConfig()


__all__ = [
    "StrategyRiskConfig",
    "strategy_risk_config",
]
