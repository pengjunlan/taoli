"""Authentication-related exceptions."""


class AuthError(Exception):
    """Base authentication exception."""


class AuthValidationError(AuthError):
    """Raised when user input does not pass validation."""


class AuthenticationFailedError(AuthError):
    """Raised when login credentials are invalid."""


class UserAlreadyExistsError(AuthError):
    """Raised when registering a duplicated username."""


class SessionExpiredError(AuthError):
    """Raised when the current session is no longer valid."""
