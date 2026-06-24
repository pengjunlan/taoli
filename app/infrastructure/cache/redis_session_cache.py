"""Redis-backed cache for auth session lookups."""

from __future__ import annotations

import logging
import socket
import time
from datetime import datetime
from typing import Any, Dict, Optional

import redis

from app.config import redis_config
from app.domain.entities import AuthSession, AuthUser


logger = logging.getLogger(__name__)


class RedisSessionCache:
    """Caches session payloads to reduce repeated database reads."""

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None
        self._available = False
        self._initialized = False
        self._last_connect_attempt_monotonic: float | None = None
        self._connect_retry_interval_seconds = 5.0
        self._socket_probe_timeout_seconds = min(max(float(redis_config.socket_timeout), 0.1), 0.25)

    def initialize(self) -> None:
        if self._initialized:
            self._ensure_connected()
            return
        self._initialized = True
        self._ensure_connected()

    def _ensure_connected(self, *, force_retry: bool = False) -> None:
        if not redis_config.session_enabled:
            return
        if self._available and self._client is not None and not force_retry:
            return
        now = time.monotonic()
        if (
            not force_retry
            and self._last_connect_attempt_monotonic is not None
            and (now - self._last_connect_attempt_monotonic) < self._connect_retry_interval_seconds
        ):
            return
        self._last_connect_attempt_monotonic = now
        if not self._probe_socket():
            self._client = None
            self._available = False
            return
        try:
            self._client = redis.Redis(
                host=redis_config.host,
                port=redis_config.port,
                password=redis_config.password,
                db=redis_config.db,
                decode_responses=True,
                socket_timeout=redis_config.socket_timeout,
                socket_connect_timeout=redis_config.socket_timeout,
            )
            self._client.ping()
            self._available = True
            self._last_connect_attempt_monotonic = None
        except Exception as exc:  # noqa: BLE001
            self._client = None
            self._available = False
            logger.warning("Redis session cache is unavailable: %s", exc)

    def _probe_socket(self) -> bool:
        try:
            with socket.create_connection(
                (redis_config.host, int(redis_config.port)),
                timeout=self._socket_probe_timeout_seconds,
            ):
                return True
        except OSError:
            return False

    @property
    def is_available(self) -> bool:
        return self._available and self._client is not None

    def store(self, session: AuthSession, ttl_seconds: int) -> None:
        client = self._get_client()
        if client is None:
            return

        key = self._build_key(session.session_token_hash)
        try:
            client.hset(
            key,
            mapping={
                "user_id": session.user.id,
                "username": session.user.username,
                "password_hash": session.user.password_hash,
                "is_active": int(session.user.is_active),
                "is_admin": int(session.user.is_admin),
                "user_created_at": session.user.created_at.isoformat(),
                "user_updated_at": session.user.updated_at.isoformat(),
                "last_login_at": session.user.last_login_at.isoformat()
                if session.user.last_login_at
                else "",
                "expires_at": session.expires_at.isoformat(),
                "created_at": session.created_at.isoformat(),
            },
        )
            client.expire(key, ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            self._mark_unavailable(exc)

    def fetch(self, session_token_hash: str) -> Optional[AuthSession]:
        client = self._get_client()
        if client is None:
            return None

        try:
            data = client.hgetall(self._build_key(session_token_hash))
        except Exception as exc:  # noqa: BLE001
            self._mark_unavailable(exc)
            client = self._get_client(force_retry=True)
            if client is None:
                return None
            try:
                data = client.hgetall(self._build_key(session_token_hash))
            except Exception as retry_exc:  # noqa: BLE001
                self._mark_unavailable(retry_exc)
                return None
        if not data:
            return None
        return self._build_session(session_token_hash, data)

    def delete(self, session_token_hash: str) -> None:
        client = self._get_client()
        if client is None:
            return

        try:
            client.delete(self._build_key(session_token_hash))
        except Exception as exc:  # noqa: BLE001
            self._mark_unavailable(exc)

    def _build_key(self, session_token_hash: str) -> str:
        return f"{redis_config.key_prefix}{session_token_hash}"

    def _build_session(self, session_token_hash: str, data: Dict[str, Any]) -> AuthSession:
        user = AuthUser(
            id=int(data["user_id"]),
            username=str(data["username"]),
            password_hash=str(data["password_hash"]),
            is_active=bool(int(data["is_active"])),
            is_admin=bool(int(data.get("is_admin", 0))),
            created_at=datetime.fromisoformat(str(data["user_created_at"])),
            updated_at=datetime.fromisoformat(str(data["user_updated_at"])),
            last_login_at=datetime.fromisoformat(str(data["last_login_at"]))
            if data.get("last_login_at")
            else None,
        )
        return AuthSession(
            user=user,
            session_token_hash=session_token_hash,
            expires_at=datetime.fromisoformat(str(data["expires_at"])),
            created_at=datetime.fromisoformat(str(data["created_at"])),
        )

    def _get_client(self, *, force_retry: bool = False) -> Optional[redis.Redis]:
        self._ensure_connected(force_retry=force_retry)
        if not self._available or self._client is None:
            return None
        return self._client

    def _mark_unavailable(self, exc: Exception) -> None:
        self._client = None
        self._available = False
        self._last_connect_attempt_monotonic = None
        logger.warning("Redis session cache connection lost: %s", exc)


redis_session_cache = RedisSessionCache()
