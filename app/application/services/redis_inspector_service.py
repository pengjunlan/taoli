"""Read-only Redis inspection service for admin pages."""

from __future__ import annotations

import json
import math
import socket
from datetime import datetime
from typing import Any, Dict, List

try:
    import redis
except ModuleNotFoundError:  # pragma: no cover - env dependent fallback
    redis = None  # type: ignore[assignment]

from app.application.services.auto_transfer_runtime_guard_service import AUTO_TRANSFER_BLOCK_HASH_KEY
from app.application.services.monitor_center_service import RUNTIME_CACHE_HASH_KEY
from app.config import redis_config


RUNTIME_NAMESPACE = "arbitrage_system:runtime:"
SCAN_COUNT = 200
INSPECTOR_SOCKET_TIMEOUT_SECONDS = 1.0
GROUP_PAGE_SIZE_DEFAULT = 20
FIXED_GROUP_DEFINITIONS = [
    ("account_balance", "账户余额缓存"),
    ("market_runtime", "行情运行时缓存"),
    ("monitor_center", "线程监控缓存"),
    ("opportunity_runtime", "机会列表缓存"),
    ("strategy_runtime", "策略运行态缓存"),
    ("auto_transfer_guard", "自动划拨守护缓存"),
    ("arbitrage_cooldown", "套利冷却缓存"),
    ("auth_session", "登录会话缓存"),
    ("other", "其他缓存"),
]


class RedisInspectorService:
    def build_overview(self) -> Dict[str, object]:
        client = self._build_client()
        is_available = client is not None
        groups = self._build_group_summaries(client) if is_available else []
        total_keys = sum(int(group.get("key_count") or 0) for group in groups)
        runtime_key_count = sum(
            int(group.get("key_count") or 0)
            for group in groups
            if str(group.get("source") or "") == "runtime"
        )
        session_key_count = sum(
            int(group.get("key_count") or 0)
            for group in groups
            if str(group.get("source") or "") == "session"
        )
        return {
            "summary_cards": self._build_summary_cards(
                is_available=is_available,
                total_keys=total_keys,
                runtime_key_count=runtime_key_count,
                session_key_count=session_key_count,
            ),
            "groups": groups,
            "group_count": len(groups),
            "key_count": total_keys,
            "is_available": is_available,
        }

    def build_group_page(
        self,
        *,
        group_key: str,
        page: int,
        page_size: int,
    ) -> Dict[str, object]:
        client = self._build_client()
        if client is None:
            return {
                "group_key": group_key,
                "group_label": self._group_label(group_key),
                "key_count": 0,
                "page": max(1, int(page or 1)),
                "page_size": max(1, int(page_size or GROUP_PAGE_SIZE_DEFAULT)),
                "page_count": 0,
                "items": [],
                "is_available": False,
            }

        effective_group_key = str(group_key or "").strip()
        items = self._load_group_entries(client, effective_group_key)
        effective_page_size = max(1, int(page_size or GROUP_PAGE_SIZE_DEFAULT))
        key_count = len(items)
        page_count = max(1, math.ceil(key_count / effective_page_size)) if key_count else 0
        effective_page = max(1, min(max(1, int(page or 1)), page_count or 1))
        start = (effective_page - 1) * effective_page_size
        end = start + effective_page_size
        return {
            "group_key": effective_group_key,
            "group_label": self._group_label(effective_group_key),
            "key_count": key_count,
            "page": effective_page,
            "page_size": effective_page_size,
            "page_count": page_count,
            "items": items[start:end],
            "is_available": True,
        }

    def _build_group_summaries(self, client) -> List[Dict[str, object]]:
        runtime_keys = self._scan_runtime_keys(client)
        session_keys = self._scan_session_keys(client)
        counts: dict[tuple[str, str], int] = {}

        for key in runtime_keys:
            group_key = self._group_key(key=key, source="runtime")
            counts[(group_key, "runtime")] = counts.get((group_key, "runtime"), 0) + self._entry_count_for_key(
                client,
                logical_key=key,
                redis_key=self._runtime_redis_key(key),
                source="runtime",
            )

        for key in session_keys:
            group_key = self._group_key(key=key, source="session")
            counts[(group_key, "session")] = counts.get((group_key, "session"), 0) + 1

        discovered_group_keys = [group_key for group_key, _ in counts.keys()]
        groups: List[Dict[str, object]] = []
        for group_key in self._ordered_group_keys(discovered_group_keys):
            source = "session" if group_key == "auth_session" else "runtime"
            key_count = int(counts.get((group_key, source), 0))
            groups.append(
                {
                    "group_key": group_key,
                    "group_label": self._group_label(group_key),
                    "key_count": key_count,
                    "source": source,
                }
            )
        return groups

    def _load_group_entries(self, client, group_key: str) -> List[Dict[str, object]]:
        if str(group_key or "") == "auth_session":
            return self._load_session_group_entries(client)

        result: List[Dict[str, object]] = []
        for logical_key in self._scan_runtime_keys(client):
            if self._group_key(key=logical_key, source="runtime") != group_key:
                continue
            redis_key = self._runtime_redis_key(logical_key)
            raw_type = self._read_type(client, redis_key)
            ttl_seconds = self._read_ttl(client, redis_key)
            payload = self._read_generic_value(client, redis_key, raw_type)
            result.extend(
                self._build_entries(
                    key=logical_key,
                    redis_key=redis_key,
                    raw_type=raw_type,
                    payload=payload,
                    ttl_seconds=ttl_seconds,
                    source="runtime",
                )
            )
        return self._sort_entries(group_key, result)

    def _load_session_group_entries(self, client) -> List[Dict[str, object]]:
        prefix = redis_config.key_prefix
        result: List[Dict[str, object]] = []
        for logical_key in self._scan_session_keys(client):
            redis_key = f"{prefix}{logical_key}"
            raw_type = self._read_type(client, redis_key)
            ttl_seconds = self._read_ttl(client, redis_key)
            payload = self._read_generic_value(client, redis_key, raw_type)
            result.extend(
                self._build_entries(
                    key=logical_key,
                    redis_key=redis_key,
                    raw_type=raw_type,
                    payload=payload,
                    ttl_seconds=ttl_seconds,
                    source="session",
                )
            )
        return self._sort_entries("auth_session", result)

    def _scan_runtime_keys(self, client) -> List[str]:
        if client is None:
            return []
        try:
            keys: List[str] = []
            for redis_key in client.scan_iter(match=f"{RUNTIME_NAMESPACE}*", count=SCAN_COUNT):
                logical_key = (
                    redis_key[len(RUNTIME_NAMESPACE) :]
                    if redis_key.startswith(RUNTIME_NAMESPACE)
                    else redis_key
                )
                if not logical_key:
                    continue
                if logical_key in {RUNTIME_CACHE_HASH_KEY, AUTO_TRANSFER_BLOCK_HASH_KEY}:
                    keys.append(logical_key)
                    continue
                if logical_key.startswith("monitor-center:worker:"):
                    continue
                if logical_key.startswith("auto-transfer:block:user:"):
                    continue
                keys.append(logical_key)
            deduped = sorted(set(keys))
            return deduped
        except Exception:
            return []

    def _scan_session_keys(self, client) -> List[str]:
        if client is None:
            return []
        prefix = redis_config.key_prefix
        try:
            result: List[str] = []
            for key in client.scan_iter(match=f"{prefix}*", count=SCAN_COUNT):
                logical_key = key[len(prefix) :] if key.startswith(prefix) else key
                if logical_key:
                    result.append(logical_key)
            return sorted(set(result))
        except Exception:
            return []

    def _entry_count_for_key(
        self,
        client,
        *,
        logical_key: str,
        redis_key: str,
        source: str,
    ) -> int:
        normalized = str(logical_key or "").lower()
        if source == "runtime" and normalized.startswith("opportunity:") and self._read_type(client, redis_key) == "hash":
            try:
                return int(client.hlen(redis_key) or 0)
            except Exception:
                return 0
        if logical_key == RUNTIME_CACHE_HASH_KEY or logical_key == AUTO_TRANSFER_BLOCK_HASH_KEY:
            try:
                return int(client.hlen(redis_key) or 0)
            except Exception:
                return 0
        return 1

    def _build_entries(
        self,
        *,
        key: str,
        redis_key: str,
        raw_type: str,
        payload: Any,
        ttl_seconds: int | None,
        source: str,
    ) -> List[Dict[str, object]]:
        group = self._group_key(key=key, source=source)
        normalized_type = str(raw_type or "").lower()
        should_expand_hash = (
            isinstance(payload, dict)
            and normalized_type == "hash"
            and (
                group == "opportunity_runtime"
                or key in {RUNTIME_CACHE_HASH_KEY, AUTO_TRANSFER_BLOCK_HASH_KEY}
            )
        )
        if not should_expand_hash:
            return [
                self._build_entry(
                    key=key,
                    redis_key=redis_key,
                    payload=payload,
                    ttl_seconds=ttl_seconds,
                    source=source,
                )
            ]

        entries: List[Dict[str, object]] = []
        for index, (field, value) in enumerate(sorted(payload.items(), key=lambda item: str(item[0])), start=1):
            effective_payload = value
            if isinstance(value, dict) and isinstance(value.get("row"), dict):
                effective_payload = value.get("row")
            display_key = f"{key}#{field}"
            entry = self._build_entry(
                key=display_key,
                redis_key=redis_key,
                payload=effective_payload,
                ttl_seconds=ttl_seconds,
                source=source,
            )
            entry["hash_field"] = str(field)
            entry["hash_key"] = key
            entry["sort_index"] = self._resolve_hash_row_sort_index(value, fallback=index)
            entries.append(entry)
        return entries

    def _build_entry(
        self,
        *,
        key: str,
        redis_key: str,
        payload: Any,
        ttl_seconds: int | None,
        source: str,
    ) -> Dict[str, object]:
        return {
            "key": key,
            "redis_key": redis_key,
            "source": source,
            "group": self._group_key(key=key, source=source),
            "type": self._payload_type(payload),
            "ttl_seconds": ttl_seconds,
            "ttl_label": self._format_ttl(ttl_seconds),
            "preview": self._build_preview(payload),
            "json_pretty": self._to_pretty_json(payload),
            "field_rows": self._build_field_rows(payload),
            "item_count": self._payload_size(payload),
        }

    def _sort_entries(self, group_key: str, entries: List[Dict[str, object]]) -> List[Dict[str, object]]:
        if group_key == "opportunity_runtime":
            return sorted(
                entries,
                key=lambda item: (
                    int(item.get("sort_index") or 10**9),
                    str(item.get("key") or ""),
                ),
            )
        return sorted(entries, key=lambda item: str(item.get("key") or ""))

    def _build_summary_cards(
        self,
        *,
        is_available: bool,
        total_keys: int,
        runtime_key_count: int,
        session_key_count: int,
    ) -> List[Dict[str, str]]:
        status_change = (
            "Redis 已连接，运行时缓存和会话缓存可正常读取。"
            if is_available
            else "Redis 当前不可用，页面暂时无法读取缓存数据。"
        )
        return [
            {
                "key": "redis_status",
                "label": "Redis 连接",
                "value": "可用" if is_available else "不可用",
                "change": status_change,
                "tone": "positive" if is_available else "warning",
            },
            {
                "key": "redis_keys",
                "label": "缓存键数量",
                "value": str(total_keys),
                "change": "当前页面可识别并展示的 Redis 键总数",
                "tone": "brand",
            },
            {
                "key": "runtime_keys",
                "label": "运行时键",
                "value": str(runtime_key_count),
                "change": f"来自 {RUNTIME_NAMESPACE} 命名空间",
                "tone": "positive",
            },
            {
                "key": "session_keys",
                "label": "会话键",
                "value": str(session_key_count),
                "change": "认证登录相关 session 缓存键",
                "tone": "warning",
            },
        ]

    def _build_client(self):
        if redis is None:
            return None
        if not self._probe_socket():
            return None
        try:
            client = redis.Redis(
                host=redis_config.host,
                port=redis_config.port,
                password=redis_config.password,
                db=redis_config.db,
                decode_responses=True,
                socket_timeout=min(float(redis_config.socket_timeout), INSPECTOR_SOCKET_TIMEOUT_SECONDS),
                socket_connect_timeout=min(float(redis_config.socket_timeout), INSPECTOR_SOCKET_TIMEOUT_SECONDS),
            )
            client.ping()
            return client
        except Exception:
            return None

    def _probe_socket(self) -> bool:
        try:
            with socket.create_connection(
                (redis_config.host, int(redis_config.port)),
                timeout=min(float(redis_config.socket_timeout), INSPECTOR_SOCKET_TIMEOUT_SECONDS),
            ):
                return True
        except OSError:
            return False

    def _read_ttl(self, client, key: str) -> int | None:
        if client is None:
            return None
        try:
            return int(client.ttl(key))
        except Exception:
            return None

    def _read_type(self, client, key: str) -> str:
        if client is None:
            return ""
        try:
            return str(client.type(key) or "")
        except Exception:
            return ""

    def _read_generic_value(self, client, key: str, raw_type: str) -> Any:
        normalized = str(raw_type or "").lower()
        try:
            if normalized == "hash":
                return self._decode_hash_mapping(client.hgetall(key))
            if normalized == "list":
                return client.lrange(key, 0, 49)
            if normalized == "set":
                return sorted(client.smembers(key))
            if normalized == "zset":
                return client.zrange(key, 0, 49, withscores=True)
            if normalized == "string":
                raw_value = client.get(key)
                return self._decode_possible_json(raw_value)
        except Exception:
            return None
        return None

    def _decode_hash_mapping(self, mapping: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field, raw_value in (mapping or {}).items():
            result[str(field)] = self._decode_possible_json(raw_value)
        return result

    def _decode_possible_json(self, value: Any) -> Any:
        text = str(value or "").strip()
        if not text:
            return value
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value

    def _group_key(self, *, key: str, source: str) -> str:
        normalized = str(key or "").lower()
        if source == "session":
            return "auth_session"
        if normalized == RUNTIME_CACHE_HASH_KEY or normalized.startswith("monitor-center:worker:"):
            return "monitor_center"
        if normalized.startswith("account-balance:"):
            return "account_balance"
        if normalized.startswith("market:ticker:") or normalized.startswith("market:funding:"):
            return "market_runtime"
        if normalized.startswith("opportunity:funding:") or normalized.startswith("opportunity:spread:"):
            return "opportunity_runtime"
        if normalized.startswith("strategy-runtime:"):
            return "strategy_runtime"
        if normalized == AUTO_TRANSFER_BLOCK_HASH_KEY or normalized.startswith("auto-transfer:block:"):
            return "auto_transfer_guard"
        if normalized.startswith("arbitrage:cooldown:"):
            return "arbitrage_cooldown"
        return "other"

    def _group_label(self, group_key: str) -> str:
        mapping = dict(FIXED_GROUP_DEFINITIONS)
        return mapping.get(group_key, group_key)

    def _ordered_group_keys(self, discovered_keys) -> List[str]:
        fixed_keys = [group_key for group_key, _ in FIXED_GROUP_DEFINITIONS]
        discovered = {
            str(group_key or "").strip()
            for group_key in discovered_keys
            if str(group_key or "").strip()
        }
        extras = sorted(group_key for group_key in discovered if group_key not in fixed_keys)
        return fixed_keys + extras

    def _payload_type(self, payload: Any) -> str:
        if isinstance(payload, dict):
            return "object"
        if isinstance(payload, list):
            return "array"
        if payload is None:
            return "null"
        return type(payload).__name__

    def _payload_size(self, payload: Any) -> int:
        if isinstance(payload, dict):
            return len(payload)
        if isinstance(payload, list):
            return len(payload)
        return 1 if payload not in {None, ""} else 0

    def _build_preview(self, payload: Any) -> str:
        if isinstance(payload, dict):
            keys = list(payload.keys())[:6]
            return "字段: " + ", ".join(str(item) for item in keys) if keys else "空对象"
        if isinstance(payload, list):
            return f"数组，共 {len(payload)} 项"
        text = str(payload or "").strip()
        if not text:
            return "空值"
        return text[:160]

    def _build_field_rows(self, payload: Any) -> List[Dict[str, str]]:
        if isinstance(payload, dict):
            rows = []
            for key, value in list(payload.items())[:20]:
                rows.append(
                    {
                        "field": str(key),
                        "value": self._stringify_value(value),
                    }
                )
            return rows
        if isinstance(payload, list):
            rows = []
            for index, value in enumerate(payload[:20], start=1):
                rows.append(
                    {
                        "field": f"item_{index}",
                        "value": self._stringify_value(value),
                    }
                )
            return rows
        return [
            {
                "field": "value",
                "value": self._stringify_value(payload),
            }
        ]

    def _stringify_value(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=False, default=self._json_default)[:240]
            except TypeError:
                return str(value)[:240]
        if value is None:
            return "null"
        return str(value)[:240]

    def _to_pretty_json(self, payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, indent=2, default=self._json_default)
        except TypeError:
            return str(payload)

    def _json_default(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def _resolve_hash_row_sort_index(self, payload: Any, *, fallback: int) -> int:
        if isinstance(payload, dict):
            row = payload.get("row")
            if isinstance(row, dict):
                try:
                    return int(row.get("rank") or fallback)
                except (TypeError, ValueError):
                    return fallback
        return fallback

    def _runtime_redis_key(self, logical_key: str) -> str:
        return f"{RUNTIME_NAMESPACE}{logical_key}"

    def _format_ttl(self, ttl_seconds: int | None) -> str:
        if ttl_seconds is None:
            return "--"
        if ttl_seconds < 0:
            return "永久"
        minutes, seconds = divmod(ttl_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        if days > 0:
            return f"{days}天 {hours}小时"
        if hours > 0:
            return f"{hours}小时 {minutes}分钟"
        if minutes > 0:
            return f"{minutes}分钟 {seconds}秒"
        return f"{seconds}秒"


redis_inspector_service = RedisInspectorService()
