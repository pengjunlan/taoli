"""Domain entities for monitoring and decision data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceHeartbeat:
    name: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class AccountSnapshot:
    account_name: str
    exchange: str
    available_margin: float
    risk_level: str
    is_online: bool


@dataclass(frozen=True)
class MarketOpportunity:
    symbol: str
    strategy_type: str
    score: float
    open_signal: bool
    close_signal: bool


@dataclass(frozen=True)
class TradeDecision:
    symbol: str
    action: str
    reason: str
    should_execute: bool
