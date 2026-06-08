"""Central application settings."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthSettings:
    session_cookie_name: str = os.getenv("ARBI_SESSION_COOKIE_NAME", "arbi_session")
    session_ttl_seconds: int = int(os.getenv("ARBI_SESSION_TTL_SECONDS", str(60 * 60 * 12)))
    remember_me_ttl_seconds: int = int(os.getenv("ARBI_REMEMBER_ME_TTL_SECONDS", str(60 * 60 * 24 * 30)))
    pbkdf2_iterations: int = int(os.getenv("ARBI_PBKDF2_ITERATIONS", "200000"))
    min_username_length: int = int(os.getenv("ARBI_MIN_USERNAME_LENGTH", "4"))
    max_username_length: int = int(os.getenv("ARBI_MAX_USERNAME_LENGTH", "32"))
    min_password_length: int = int(os.getenv("ARBI_MIN_PASSWORD_LENGTH", "8"))
    secure_cookie: bool = os.getenv("ARBI_SECURE_COOKIE", "false").strip().lower() in {"1", "true", "yes", "on"}
    same_site: str = os.getenv("ARBI_SAME_SITE", "lax")


@dataclass(frozen=True)
class AppSettings:
    auth: AuthSettings = AuthSettings()


settings = AppSettings()
