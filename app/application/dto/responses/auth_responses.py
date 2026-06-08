"""Auth response DTOs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict


@dataclass(frozen=True)
class AuthResponse:
    success: bool
    message: str
    redirect_url: str = ""

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        if not payload["redirect_url"]:
            payload.pop("redirect_url")
        return payload
