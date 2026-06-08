"""Security helpers for password hashing and session tokens."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from app.config import settings


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> None:
    normalized = normalize_username(username)
    auth_settings = settings.auth
    if not normalized:
        raise ValueError("请输入账号。")
    if len(normalized) < auth_settings.min_username_length:
        raise ValueError(f"账号至少需要 {auth_settings.min_username_length} 个字符。")
    if len(normalized) > auth_settings.max_username_length:
        raise ValueError(f"账号不能超过 {auth_settings.max_username_length} 个字符。")
    if not USERNAME_PATTERN.match(normalized):
        raise ValueError("账号仅支持字母、数字、下划线和中划线。")


def validate_password(password: str) -> None:
    auth_settings = settings.auth
    if not password:
        raise ValueError("请输入密码。")
    if len(password) < auth_settings.min_password_length:
        raise ValueError(f"密码至少需要 {auth_settings.min_password_length} 个字符。")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = settings.auth.pbkdf2_iterations
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
    ).hex()
    return f"{iterations}${salt}${password_hash}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        iterations_text, salt, expected_hash = stored_hash.split("$", 2)
        iterations = int(iterations_text)
    except (TypeError, ValueError):
        return False

    candidate_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate_hash, expected_hash)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(session_token: str) -> str:
    return hashlib.sha256(session_token.encode("utf-8")).hexdigest()
