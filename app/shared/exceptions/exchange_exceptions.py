"""Exchange-related exceptions."""


class ExchangeError(Exception):
    """Base exchange exception."""


class ExchangeValidationError(ExchangeError):
    """Raised when submitted exchange credentials are incomplete or invalid."""


class ExchangeConnectionError(ExchangeError):
    """Raised when an exchange connection test fails."""
