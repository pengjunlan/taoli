"""Account domain entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExchangeAccount:
    id: int
    user_id: int
    market_type: str
    exchange_code: str
    account_name: str
    api_key: str
    api_secret: str
    api_passphrase: str
    connection_test_status: str
    funding_ratio_percent: float
    current_available_amount: float
    current_available_synced_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AccountAddress:
    id: int
    account_id: int
    network: str
    address_value: str
    memo_tag: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TransferRecord:
    id: int
    user_id: int
    from_account_id: int
    to_account_id: int
    amount: float
    reason: str
    status: str
    result: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AutoTransferConfig:
    id: int
    user_id: int
    is_enabled: bool
    trigger_ratio: float
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StrategyRule:
    id: int
    user_id: int
    name: str
    strategy_type: str
    annualized_rate_threshold: float
    spread_rate_threshold: float
    max_spread_rate_threshold: float
    max_pairs: int
    order_amount_usdt: float
    max_position_usdt: float
    order_interval_seconds: int
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SystemExchangeConfig:
    id: int
    exchange_code: str
    is_enabled: bool
    use_public_api: bool
    api_key: str
    api_secret: str
    api_passphrase: str
    remark: str
    created_at: datetime
    updated_at: datetime
