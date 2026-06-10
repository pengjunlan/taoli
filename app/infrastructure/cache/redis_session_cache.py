"""Redis-backed cache for auth session lookups."""

from __future__ import annotations

import logging
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

    def initialize(self) -> None:
        if not redis_config.enabled:
            return
        try:
            self._client = redis.Redis(
                host=redis_config.host,
                port=redis_config.port,
                password=redis_config.password,
                db=redis_config.db,
                decode_responses=True,
                socket_timeout=redis_config.socket_timeout,
            )
            self._client.ping()
            self._available = True
        except Exception as exc:  # noqa: BLE001
            self._client = None
            self._available = False
            logger.warning("Redis session cache is unavailable: %s", exc)

    @property
    def is_available(self) -> bool:
        return self._available and self._client is not None

    def store(self, session: AuthSession, ttl_seconds: int) -> None:
        if not self.is_available:
            return

        assert self._client is not None
        key = self._build_key(session.session_token_hash)
        self._client.hset(
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
        self._client.expire(key, ttl_seconds)

    def fetch(self, session_token_hash: str) -> Optional[AuthSession]:
        if not self.is_available:
            return None

        assert self._client is not None
        data = self._client.hgetall(self._build_key(session_token_hash))
        if not data:
            return None
        return self._build_session(session_token_hash, data)

    def delete(self, session_token_hash: str) -> None:
        if not self.is_available:
            return

        assert self._client is not None
        self._client.delete(self._build_key(session_token_hash))

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


redis_session_cache = RedisSessionCache()
