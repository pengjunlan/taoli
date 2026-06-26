"""Strategy rule request DTOs."""

from pydantic import BaseModel


class StrategyRuleCreateRequest(BaseModel):
    name: str
    strategy_type: str
    annualized_rate_threshold: float = 0
    min_net_funding_rate_threshold: float = 0
    spread_rate_threshold: float = 0
    min_close_spread_rate_threshold: float = 0
    max_spread_rate_threshold: float = 0
    max_pairs: int = 1
    order_amount_usdt: float = 0
    max_position_usdt: float = 0
    order_interval_seconds: int = 0
    funding_open_window_start_minutes: int = 0
    funding_open_window_end_minutes: int = 0
    funding_spread_resonance_min: float = 0
    net_spread_threshold: float = 0
    funding_carry_min: float = 0
    max_funding_cost: float = 0
    min_net_profit_threshold: float = 0
    take_profit_threshold: float = 0
    max_hold_minutes: int = 0
    close_interval_seconds: int = 0
    close_batch_count: int = 0
    close_batch_ratio_percent: float = 0
    single_leg_timeout_seconds: int = 0
    is_enabled: bool = True


class StrategyRuleUpdateRequest(BaseModel):
    name: str
    strategy_type: str
    annualized_rate_threshold: float = 0
    min_net_funding_rate_threshold: float = 0
    spread_rate_threshold: float = 0
    min_close_spread_rate_threshold: float = 0
    max_spread_rate_threshold: float = 0
    max_pairs: int = 1
    order_amount_usdt: float = 0
    max_position_usdt: float = 0
    order_interval_seconds: int = 0
    funding_open_window_start_minutes: int = 0
    funding_open_window_end_minutes: int = 0
    funding_spread_resonance_min: float = 0
    net_spread_threshold: float = 0
    funding_carry_min: float = 0
    max_funding_cost: float = 0
    min_net_profit_threshold: float = 0
    take_profit_threshold: float = 0
    max_hold_minutes: int = 0
    close_interval_seconds: int = 0
    close_batch_count: int = 0
    close_batch_ratio_percent: float = 0
    single_leg_timeout_seconds: int = 0
    is_enabled: bool = True
    close_positions_on_disable: bool = False
