"""Redis configuration for session cache and runtime shared state."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RedisConfig:
    host: str = os.getenv("ARBI_REDIS_HOST", "127.0.0.1")
    port: int = int(os.getenv("ARBI_REDIS_PORT", "6379"))
    password: Optional[str] = os.getenv("ARBI_REDIS_PASSWORD") or None
    db: int = int(os.getenv("ARBI_REDIS_DB", "0"))
    server_path: Optional[str] = os.getenv("ARBI_REDIS_SERVER_PATH", "").strip() or None
    enabled: bool = os.getenv("ARBI_REDIS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    session_enabled: bool = os.getenv(
        "ARBI_REDIS_SESSION_ENABLED",
        os.getenv("ARBI_REDIS_ENABLED", "true"),
    ).strip().lower() not in {"0", "false", "no", "off"}
    runtime_enabled: bool = os.getenv(
        "ARBI_REDIS_RUNTIME_ENABLED",
        os.getenv("ARBI_REDIS_ENABLED", "true"),
    ).strip().lower() not in {"0", "false", "no", "off"}
    key_prefix: str = os.getenv("ARBI_REDIS_KEY_PREFIX", "arbitrage_system:auth:session:")
    socket_timeout: int = int(os.getenv("ARBI_REDIS_SOCKET_TIMEOUT", "2"))


redis_config = RedisConfig()
