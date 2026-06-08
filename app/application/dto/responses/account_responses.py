"""Account response DTOs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict


@dataclass(frozen=True)
class AccountResponse:
    success: bool
    message: str
    account_id: int = 0

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        if not payload["account_id"]:
            payload.pop("account_id")
        return payload
