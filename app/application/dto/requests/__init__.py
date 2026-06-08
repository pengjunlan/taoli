"""Inbound request DTOs."""

from app.application.dto.requests.account_requests import AccountCreateRequest, AccountUpdateRequest
from app.application.dto.requests.auth_requests import LoginRequest, RegisterRequest

__all__ = [
    "AccountCreateRequest",
    "AccountUpdateRequest",
    "LoginRequest",
    "RegisterRequest",
]
