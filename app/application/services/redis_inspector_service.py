"""Read-only Redis inspection service for admin pages."""

from __future__ import annotations

import json
import socket
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

try:
    import redis
except ModuleNotFoundError:  # pragma: no cover - env dependent fallback
    redis = None  # type: ignore[assignment]

from app.config import redis_config


RUNTIME_NAMESPACE = "arbitrage_system:runtime:"
SCAN_COUNT = 200
INSPECTOR_SOCKET_TIMEOUT_SECONDS = 1.0
FIXED_GROUP_DEFINITIONS = [
    ("account_balance", "账户余额缓存"),
    ("market_runtime", "行情运行时缓存"),
    ("monitor_center", "线程监控缓存"),
    ("opportunity_runtime", "机会列表缓存"),
    ("strategy_runtime", "策略运行态缓存"),
    ("auto_transfer_guard", "自动调拨守护缓存"),
    ("arbitrage_cooldown", "套利冷却缓存"),
    ("auth_session", "登录会话缓存"),
    ("other", "其他缓存"),
]


class RedisInspectorService:
    def build_snapshot(self) -> Dict[str, object]:
        client = self._build_client()
        is_available = client is not None
        runtime_entries = self._load_runtime_entries(client) if is_available else []
        session_entries = self._load_session_entries(client) if is_available else []
        entries = runtime_entries + session_entries

        grouped: dict[str, list[dict]] = defaultdict(list)
        for entry in entries:
            grouped[str(entry.get("group") or "other")].append(entry)

        group_rows: List[Dict[str, object]] = []
        total_keys = 0

        for group_key in self._ordered_group_keys(grouped.keys()):
            items = sorted(
                grouped.get(group_key, []),
                key=lambda item: str(item.get("key") or ""),
            )
            total_keys += len(items)
            group_rows.append(
                {
                    "group_key": group_key,
                    "group_label": self._group_label(group_key),
                    "key_count": len(items),
                    "items": items,
                }
            )

        return {
            "summary_cards": self._build_summary_cards(
                is_available=is_available,
                total_keys=total_keys,
                runtime_key_count=len(runtime_entries),
                session_key_count=len(session_entries),
            ),
            "groups": group_rows,
            "group_count": len(group_rows),
            "key_count": total_keys,
            "is_available": is_available,
        }

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

    def _load_runtime_entries(self, client) -> List[Dict[str, object]]:
        entries: List[Dict[str, object]] = []
        if client is None:
            return entries

        try:
            for redis_key in client.scan_iter(match=f"{RUNTIME_NAMESPACE}*", count=SCAN_COUNT):
                raw_type = self._read_type(client, redis_key)
                payload = self._read_generic_value(client, redis_key, raw_type)
                logical_key = (
                    redis_key[len(RUNTIME_NAMESPACE) :]
                    if redis_key.startswith(RUNTIME_NAMESPACE)
                    else redis_key
                )
                ttl_seconds = self._read_ttl(client, redis_key)
                entries.extend(
                    self._build_entries(
                        key=logical_key,
                        redis_key=redis_key,
                        raw_type=raw_type,
                        payload=payload,
                        ttl_seconds=ttl_seconds,
                        source="runtime",
                    )
                )
        except Exception:
            return []
        return entries

    def _load_session_entries(self, client) -> List[Dict[str, object]]:
        if client is None:
            return []

        prefix = redis_config.key_prefix
        result: List[Dict[str, object]] = []
        try:
            for key in client.scan_iter(match=f"{prefix}*", count=SCAN_COUNT):
                raw_type = self._read_type(client, key)
                ttl_seconds = self._read_ttl(client, key)
                payload = self._read_generic_value(client, key, raw_type)
                logical_key = key[len(prefix) :] if key.startswith(prefix) else key
                result.extend(
                    self._build_entries(
                        key=logical_key,
                        redis_key=key,
                        raw_type=raw_type,
                        payload=payload,
                        ttl_seconds=ttl_seconds,
                        source="session",
                    )
                )
        except Exception:
            return []
        return result

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
        if group != "opportunity_runtime" or normalized_type != "hash" or not isinstance(payload, dict):
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
            entry = self._build_entry(
                key=f"{key}#{field}",
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
            ttl = int(client.ttl(key))
        except Exception:
            return None
        return ttl

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
                return client.hgetall(key)
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
        if normalized.startswith("monitor-center:worker:"):
            return "monitor_center"
        if normalized.startswith("account-balance:"):
            return "account_balance"
        if normalized.startswith("market:ticker:") or normalized.startswith("market:funding:"):
            return "market_runtime"
        if normalized.startswith("opportunity:funding:") or normalized.startswith("opportunity:spread:"):
            return "opportunity_runtime"
        if normalized.startswith("strategy-runtime:"):
            return "strategy_runtime"
        if normalized.startswith("auto-transfer:block:"):
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
