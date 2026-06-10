"""Inbound request DTOs."""

from app.application.dto.requests.account_requests import (
    AccountAutoTransferConfigRequest,
    AccountCreateRequest,
    AccountFundingRatioUpdateRequest,
    AccountTransferCreateRequest,
    AccountUpdateRequest,
)
from app.application.dto.requests.auth_requests import LoginRequest, RegisterRequest
from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.dto.requests.strategy_requests import (
    StrategyRuleCreateRequest,
    StrategyRuleUpdateRequest,
)
from app.application.dto.requests.system_exchange_requests import (
    SystemExchangeConfigUpdateRequest,
)

__all__ = [
    "AccountAutoTransferConfigRequest",
    "AccountCreateRequest",
    "AccountFundingRatioUpdateRequest",
    "AccountTransferCreateRequest",
    "AccountUpdateRequest",
    "ExchangeConnectionTestRequest",
    "LoginRequest",
    "RegisterRequest",
    "StrategyRuleCreateRequest",
    "StrategyRuleUpdateRequest",
    "SystemExchangeConfigUpdateRequest",
]
