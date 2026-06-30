"""Inbound request DTOs."""

from app.application.dto.requests.account_requests import (
    AccountAutoTransferConfigRequest,
    AccountCreateRequest,
    AccountFundingRatioUpdateRequest,
    AccountTransferCreateRequest,
    AccountUpdateRequest,
    ExchangeAssetNetworksRefreshRequest,
)
from app.application.dto.requests.auth_requests import LoginRequest, RegisterRequest
from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.dto.requests.strategy_requests import (
    StrategyRuleCreateRequest,
    StrategyRuleUpdateRequest,
)
from app.application.dto.requests.system_exchange_requests import (
    SystemAssetBlacklistUpdateRequest,
    SystemExchangeConfigUpdateRequest,
)

__all__ = [
    "AccountAutoTransferConfigRequest",
    "AccountCreateRequest",
    "AccountFundingRatioUpdateRequest",
    "AccountTransferCreateRequest",
    "AccountUpdateRequest",
    "ExchangeConnectionTestRequest",
    "ExchangeAssetNetworksRefreshRequest",
    "LoginRequest",
    "RegisterRequest",
    "StrategyRuleCreateRequest",
    "StrategyRuleUpdateRequest",
    "SystemAssetBlacklistUpdateRequest",
    "SystemExchangeConfigUpdateRequest",
]
