"""Shared exception definitions."""

from app.shared.exceptions.account_exceptions import (
    AccountError,
    AccountNotFoundError,
    AccountPersistenceError,
    AccountValidationError,
)
from app.shared.exceptions.auth_exceptions import (
    AuthError,
    AuthenticationFailedError,
    AuthValidationError,
    SessionExpiredError,
    UserAlreadyExistsError,
)

__all__ = [
    "AccountError",
    "AccountNotFoundError",
    "AccountPersistenceError",
    "AccountValidationError",
    "AuthError",
    "AuthenticationFailedError",
    "AuthValidationError",
    "SessionExpiredError",
    "UserAlreadyExistsError",
]
