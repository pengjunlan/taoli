"""Authentication domain entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    password_hash: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None


@dataclass(frozen=True)
class AuthSession:
    user: AuthUser
    session_token_hash: str
    expires_at: datetime
    created_at: datetime
