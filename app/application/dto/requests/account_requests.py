"""Account request DTOs."""

from pydantic import BaseModel


class AccountCreateRequest(BaseModel):
    market_type: str
    exchange_code: str
    api_key: str
    api_secret: str
    api_passphrase: str = ""
    connection_test_status: str = "untested"
    address_network: str = ""
    address_value: str = ""
    address_memo: str = ""


class AccountUpdateRequest(BaseModel):
    market_type: str
    exchange_code: str
    api_key: str
    api_secret: str = ""
    api_passphrase: str = ""
    connection_test_status: str = "untested"
    address_network: str = ""
    address_value: str = ""
    address_memo: str = ""


class AccountFundingRatioUpdateRequest(BaseModel):
    funding_ratio_percent: float = 0


class AccountTransferCreateRequest(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: float
    reason: str = "手动调拨"


class AccountAutoTransferConfigRequest(BaseModel):
    is_enabled: bool = True
    trigger_ratio: float = 0.5


class ExchangeAssetNetworksRefreshRequest(BaseModel):
    exchange_code: str
