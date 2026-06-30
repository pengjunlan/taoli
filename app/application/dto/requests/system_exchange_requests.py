"""System exchange configuration request DTOs."""

from pydantic import BaseModel


class SystemExchangeConfigUpdateRequest(BaseModel):
    exchange_code: str
    is_enabled: bool = True
    use_public_api: bool = True
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    remark: str = ""


class SystemAssetBlacklistUpdateRequest(BaseModel):
    asset_blacklist: str = ""
