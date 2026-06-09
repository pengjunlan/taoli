"""Exchange request DTOs."""

from pydantic import BaseModel


class ExchangeConnectionTestRequest(BaseModel):
    account_id: int = 0
    market_type: str
    exchange_code: str
    api_key: str
    api_secret: str
    api_passphrase: str = ""
