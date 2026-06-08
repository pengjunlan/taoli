"""Account-related exceptions."""


class AccountError(Exception):
    """Base account exception."""


class AccountValidationError(AccountError):
    """Raised when account input is invalid."""


class AccountPersistenceError(AccountError):
    """Raised when account data cannot be persisted."""


class AccountNotFoundError(AccountError):
    """Raised when the target account does not exist or is not accessible."""
