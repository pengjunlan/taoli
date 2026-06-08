"""Account request DTOs."""

from pydantic import BaseModel


class AccountCreateRequest(BaseModel):
    market_type: str
    exchange_code: str
    api_key: str
    api_secret: str
    api_passphrase: str = ""
    address_network: str = ""
    address_value: str = ""
    address_memo: str = ""


class AccountUpdateRequest(BaseModel):
    market_type: str
    exchange_code: str
    api_key: str
    api_secret: str = ""
    api_passphrase: str = ""
    address_network: str = ""
    address_value: str = ""
    address_memo: str = ""
