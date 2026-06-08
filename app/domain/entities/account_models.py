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
