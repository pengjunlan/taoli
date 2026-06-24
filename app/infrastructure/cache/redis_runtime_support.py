"""Shared runtime cache helpers backed by Redis only."""

from __future__ import annotations

import json
import logging
import socket
import time
from datetime import datetime
from typing import Any, Callable, Optional, TypeVar

import redis

from app.config import redis_config


logger = logging.getLogger(__name__)
T = TypeVar("T")


class RedisRuntimeSupport:
    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None
        self._redis_available = False
        self._initialized = False
        self._namespace = "arbitrage_system:runtime:"
        self._last_connect_attempt_monotonic: float | None = None
        self._connect_retry_interval_seconds = 5.0
        self._socket_probe_timeout_seconds = min(max(float(redis_config.socket_timeout), 0.1), 0.25)

    def initialize(self) -> None:
        if self._initialized:
            self._ensure_connected()
            return
        self._initialized = True
        self._ensure_connected()

    def _ensure_connected(self) -> None:
        if not redis_config.runtime_enabled:
            return
        if self._redis_available and self._client is not None:
            return
        now = time.monotonic()
        if (
            self._last_connect_attempt_monotonic is not None
            and (now - self._last_connect_attempt_monotonic) < self._connect_retry_interval_seconds
        ):
            return
        self._last_connect_attempt_monotonic = now
        if not self._probe_socket():
            self._client = None
            self._redis_available = False
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
            self._redis_available = True
            self._last_connect_attempt_monotonic = None
        except Exception as exc:  # noqa: BLE001
            self._client = None
            self._redis_available = False
            logger.warning("Redis runtime cache is unavailable: %s", exc)

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
        return self._redis_available and self._client is not None

    def set_json(self, key: str, payload: Any, *, ttl_seconds: int | None = None) -> None:
        encoded_value = json.dumps(payload, ensure_ascii=False, default=self._json_default)
        namespaced_key = self.key(key)

        def _write(client: redis.Redis) -> None:
            if ttl_seconds and ttl_seconds > 0:
                client.setex(namespaced_key, ttl_seconds, encoded_value)
            else:
                client.set(namespaced_key, encoded_value)

        try:
            self._run_with_retry(_write)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Set runtime cache failed: key=%s detail=%s", key, exc)

    def sync_hash_json(
        self,
        key: str,
        field_payload_map: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        namespaced_key = self.key(key)
        encoded_mapping = {
            str(field): json.dumps(payload, ensure_ascii=False, default=self._json_default)
            for field, payload in field_payload_map.items()
            if str(field).strip()
        }

        def _write(client: redis.Redis) -> None:
            pipeline = client.pipeline()
            existing_type = str(client.type(namespaced_key) or "").lower()
            if existing_type and existing_type not in {"none", "hash"}:
                pipeline.delete(namespaced_key)
                pipeline.execute()
            existing_fields = set(client.hkeys(namespaced_key))
            next_fields = set(encoded_mapping.keys())
            stale_fields = sorted(existing_fields - next_fields)
            if stale_fields:
                pipeline.hdel(namespaced_key, *stale_fields)
            if encoded_mapping:
                pipeline.hset(namespaced_key, mapping=encoded_mapping)
            else:
                pipeline.delete(namespaced_key)
            if encoded_mapping and ttl_seconds and ttl_seconds > 0:
                pipeline.expire(namespaced_key, ttl_seconds)
            elif encoded_mapping:
                pipeline.persist(namespaced_key)
            pipeline.execute()

        try:
            self._run_with_retry(_write)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sync runtime hash cache failed: key=%s detail=%s", key, exc)

    def set_hash_field_json(
        self,
        key: str,
        field: str,
        payload: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        namespaced_key = self.key(key)
        encoded_field = str(field or "").strip()
        if not encoded_field:
            return
        encoded_value = json.dumps(payload, ensure_ascii=False, default=self._json_default)

        def _write(client: redis.Redis) -> None:
            pipeline = client.pipeline()
            existing_type = str(client.type(namespaced_key) or "").lower()
            if existing_type and existing_type not in {"none", "hash"}:
                pipeline.delete(namespaced_key)
                pipeline.execute()
            pipeline.hset(namespaced_key, encoded_field, encoded_value)
            if ttl_seconds and ttl_seconds > 0:
                pipeline.expire(namespaced_key, ttl_seconds)
            else:
                pipeline.persist(namespaced_key)
            pipeline.execute()

        try:
            self._run_with_retry(_write)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Set runtime hash field cache failed: key=%s field=%s detail=%s",
                key,
                encoded_field,
                exc,
            )

    def get_hash_json(self, key: str) -> dict[str, Any]:
        def _read(client: redis.Redis) -> dict[str, Any]:
            raw_mapping = client.hgetall(self.key(key))
            result: dict[str, Any] = {}
            for field, raw_value in raw_mapping.items():
                try:
                    result[str(field)] = json.loads(raw_value)
                except json.JSONDecodeError:
                    result[str(field)] = raw_value
            return result

        try:
            return self._run_with_retry(_read) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Get runtime hash cache failed: key=%s detail=%s", key, exc)
            return {}

    def get_hash_field_json(self, key: str, field: str) -> Any | None:
        encoded_field = str(field or "").strip()
        if not encoded_field:
            return None

        def _read(client: redis.Redis) -> Any | None:
            raw_value = client.hget(self.key(key), encoded_field)
            if not raw_value:
                return None
            try:
                return json.loads(raw_value)
            except json.JSONDecodeError:
                return raw_value

        try:
            return self._run_with_retry(_read)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Get runtime hash field cache failed: key=%s field=%s detail=%s",
                key,
                encoded_field,
                exc,
            )
            return None

    def get_json(self, key: str) -> Any | None:
        try:
            value = self._run_with_retry(lambda client: client.get(self.key(key)))
            if not value:
                return None
            return json.loads(value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Get runtime cache from redis failed: key=%s detail=%s", key, exc)
            return None

    def delete(self, key: str) -> None:
        try:
            self._run_with_retry(lambda client: client.delete(self.key(key)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Delete runtime cache failed: key=%s detail=%s", key, exc)

    def delete_hash_field(self, key: str, field: str) -> None:
        encoded_field = str(field or "").strip()
        if not encoded_field:
            return

        def _delete(client: redis.Redis) -> None:
            namespaced_key = self.key(key)
            pipeline = client.pipeline()
            pipeline.hdel(namespaced_key, encoded_field)
            pipeline.hlen(namespaced_key)
            results = pipeline.execute()
            remaining = int(results[-1] or 0)
            if remaining <= 0:
                client.delete(namespaced_key)

        try:
            self._run_with_retry(_delete)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Delete runtime hash field cache failed: key=%s field=%s detail=%s",
                key,
                encoded_field,
                exc,
            )

    def list_json(self, pattern: str) -> list[tuple[str, Any]]:
        result: list[tuple[str, Any]] = []
        namespaced_pattern = self.key(pattern)

        def _read(client: redis.Redis) -> list[tuple[str, Any]]:
            items: list[tuple[str, Any]] = []
            for raw_key in client.scan_iter(match=namespaced_pattern, count=200):
                value = client.get(raw_key)
                if not value:
                    continue
                try:
                    payload = json.loads(value)
                except json.JSONDecodeError:
                    continue
                logical_key = raw_key[len(self._namespace) :] if raw_key.startswith(self._namespace) else raw_key
                items.append((logical_key, payload))
            return items

        try:
            result = self._run_with_retry(_read) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("List runtime cache failed: pattern=%s detail=%s", pattern, exc)
        return result

    def key(self, key: str) -> str:
        return f"{self._namespace}{key}"

    def _json_default(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return {"__datetime__": value.isoformat()}
        return str(value)

    def parse_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, dict) and "__datetime__" in value:
            text = str(value.get("__datetime__") or "").strip()
            if text:
                try:
                    return datetime.fromisoformat(text)
                except ValueError:
                    return None
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.strip())
            except ValueError:
                return None
        return None

    def _run_with_retry(self, operation: Callable[[redis.Redis], T]) -> T | None:
        client = self._get_connected_client()
        if client is None:
            return None

        try:
            return operation(client)
        except Exception as exc:  # noqa: BLE001
            self._mark_unavailable(exc)
            retry_client = self._get_connected_client(force_retry=True)
            if retry_client is None:
                raise
            return operation(retry_client)

    def _get_connected_client(self, *, force_retry: bool = False) -> Optional[redis.Redis]:
        if force_retry:
            self._last_connect_attempt_monotonic = None
        self._ensure_connected()
        if not self._redis_available or self._client is None:
            return None
        return self._client

    def _mark_unavailable(self, exc: Exception) -> None:
        self._client = None
        self._redis_available = False
        self._last_connect_attempt_monotonic = None
        logger.warning("Redis runtime cache connection lost: %s", exc)


redis_runtime_support = RedisRuntimeSupport()
