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
    maker_fee_rate: float
    taker_fee_rate: float
    fee_rate_synced_at: datetime | None
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
class ExchangeAssetNetwork:
    id: int
    exchange_code: str
    asset_code: str
    network_code: str
    network_name: str
    network_id: str
    is_deposit_enabled: bool
    is_withdraw_enabled: bool
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
    execute_status: str
    result_status: str
    failure_type: str
    failure_reason: str
    config_fingerprint: str
    execution_checkpoint: str
    execution_reference: str
    execution_payload: str
    processed_at: datetime | None
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
    min_net_funding_rate_threshold: float
    spread_rate_threshold: float
    open_spread_rate_max_threshold: float
    min_close_spread_rate_threshold: float
    max_spread_rate_threshold: float
    max_pairs: int
    order_amount_usdt: float
    max_position_usdt: float
    order_interval_seconds: int
    split_order_amount_usdt: float
    funding_open_window_start_minutes: int
    funding_open_window_end_minutes: int
    funding_settlement_skew_minutes: int
    funding_spread_resonance_min: float
    net_spread_threshold: float
    funding_carry_min: float
    max_funding_cost: float
    min_net_profit_threshold: float
    take_profit_threshold: float
    drawdown_add_step_percent: float
    max_hold_minutes: int
    close_interval_seconds: int
    close_batch_count: int
    close_batch_ratio_percent: float
    single_leg_timeout_seconds: int
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


@dataclass(frozen=True)
class SystemRuntimeConfig:
    id: int
    config_key: str
    config_value: str
    remark: str
    created_at: datetime
    updated_at: datetime
