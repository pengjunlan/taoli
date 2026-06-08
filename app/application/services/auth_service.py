"""Authentication service for register, login, logout and session validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import mysql.connector

from app.application.dto.requests import LoginRequest, RegisterRequest
from app.config import settings
from app.domain.entities import AuthSession, AuthUser
from app.infrastructure.cache import redis_session_cache
from app.infrastructure.persistence.auth_repository import auth_repository
from app.shared.exceptions import (
    AuthenticationFailedError,
    AuthValidationError,
    SessionExpiredError,
    UserAlreadyExistsError,
)
from app.shared.utils import (
    generate_session_token,
    hash_password,
    hash_session_token,
    normalize_username,
    validate_password,
    validate_username,
    verify_password,
)


@dataclass(frozen=True)
class AuthResult:
    user: AuthUser
    session_token: str
    ttl_seconds: int


class AuthService:
    """Coordinates auth validation, storage and session lifecycle."""

    def register(self, payload: RegisterRequest) -> None:
        username = normalize_username(payload.username)
        self._validate_registration_input(username, payload.password, payload.confirm_password)

        password_hash = hash_password(payload.password)
        try:
            auth_repository.create_user(username, password_hash)
        except mysql.connector.IntegrityError as exc:
            raise UserAlreadyExistsError("该账号已存在，请直接登录。") from exc

    def login(
        self,
        payload: LoginRequest,
        ip_address: str,
        user_agent: str,
    ) -> AuthResult:
        username = normalize_username(payload.username)
        try:
            validate_username(username)
            validate_password(payload.password)
        except ValueError as exc:
            raise AuthValidationError(str(exc)) from exc

        user = auth_repository.get_user_by_username(username)
        if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
            auth_repository.write_login_log(
                username=username,
                is_success=False,
                failure_reason="invalid_credentials",
                ip_address=ip_address,
                user_agent=user_agent,
                user_id=user.id if user else None,
            )
            raise AuthenticationFailedError("账号或密码错误。")

        ttl_seconds = (
            settings.auth.remember_me_ttl_seconds
            if payload.remember_me
            else settings.auth.session_ttl_seconds
        )
        session_token = generate_session_token()
        session_token_hash = hash_session_token(session_token)
        expires_at = self._utcnow() + timedelta(seconds=ttl_seconds)

        auth_repository.create_session(
            user_id=user.id,
            session_token_hash=session_token_hash,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        auth_repository.update_last_login(user.id)

        refreshed_user = auth_repository.get_user_by_id(user.id)
        assert refreshed_user is not None

        session = AuthSession(
            user=refreshed_user,
            session_token_hash=session_token_hash,
            expires_at=expires_at,
            created_at=self._utcnow(),
        )
        redis_session_cache.store(session, ttl_seconds)
        auth_repository.write_login_log(
            username=username,
            is_success=True,
            failure_reason=None,
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=user.id,
        )
        return AuthResult(
            user=refreshed_user,
            session_token=session_token,
            ttl_seconds=ttl_seconds,
        )

    def resolve_user_from_session(self, session_token: str) -> AuthUser:
        if not session_token:
            raise SessionExpiredError("未检测到登录状态。")

        session_token_hash = hash_session_token(session_token)
        session = redis_session_cache.fetch(session_token_hash)
        if session is None:
            session = auth_repository.get_active_session(session_token_hash)
            if session is None:
                raise SessionExpiredError("登录状态已失效，请重新登录。")

            ttl_seconds = max(1, int((session.expires_at - self._utcnow()).total_seconds()))
            redis_session_cache.store(session, ttl_seconds)

        if session.expires_at <= self._utcnow():
            self.logout(session_token)
            raise SessionExpiredError("登录状态已过期，请重新登录。")

        auth_repository.touch_session(session_token_hash)
        return session.user

    def logout(self, session_token: str) -> None:
        if not session_token:
            return

        session_token_hash = hash_session_token(session_token)
        auth_repository.revoke_session(session_token_hash)
        redis_session_cache.delete(session_token_hash)

    def _validate_registration_input(self, username: str, password: str, confirm_password: str) -> None:
        try:
            validate_username(username)
            validate_password(password)
        except ValueError as exc:
            raise AuthValidationError(str(exc)) from exc

        if password != confirm_password:
            raise AuthValidationError("两次输入的密码不一致。")

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)


auth_service = AuthService()
