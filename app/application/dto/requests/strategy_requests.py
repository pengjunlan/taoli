"""Strategy rule request DTOs."""

from pydantic import BaseModel


class StrategyRuleCreateRequest(BaseModel):
    name: str
    strategy_type: str
    annualized_rate_threshold: float = 0
    spread_rate_threshold: float = 0
    max_spread_rate_threshold: float = 0
    max_pairs: int = 1
    order_amount_usdt: float = 0
    max_position_usdt: float = 0
    order_interval_seconds: int = 0
    is_enabled: bool = True


class StrategyRuleUpdateRequest(BaseModel):
    name: str
    strategy_type: str
    annualized_rate_threshold: float = 0
    spread_rate_threshold: float = 0
    max_spread_rate_threshold: float = 0
    max_pairs: int = 1
    order_amount_usdt: float = 0
    max_position_usdt: float = 0
    order_interval_seconds: int = 0
    is_enabled: bool = True
