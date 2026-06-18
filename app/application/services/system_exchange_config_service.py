"""System exchange config service."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from app.application.dto.requests import SystemExchangeConfigUpdateRequest
from app.application.services.swap_market_rules import is_u_margin_linear_swap_market
from app.domain.entities import AuthUser
from app.infrastructure.cache import market_runtime_cache
from app.infrastructure.persistence.market_repository import market_repository
from app.infrastructure.persistence.system_exchange_repository import system_exchange_repository
from app.shared.exceptions import AccountPersistenceError, AccountValidationError


EXCHANGE_LABELS = {
    "binance": "Binance",
    "bitget": "Bitget",
    "okx": "OKX",
    "gate": "Gate",
    "htx": "HTX",
}

MARKET_FEED_STALE_SECONDS = 90


class SystemExchangeConfigService:
    def list_config_rows(self) -> List[Dict[str, object]]:
        rows = system_exchange_repository.list_configs()
        exchange_codes = [str(row.get("exchange_code") or "").strip().lower() for row in rows]
        feed_status_map = self._build_market_feed_status_map(exchange_codes)
        return [self._build_row(row, feed_status_map=feed_status_map) for row in rows]

    def get_config_map(self) -> Dict[str, Dict[str, object]]:
        rows = system_exchange_repository.list_configs()
        return {
            str(row["exchange_code"]): {
                "exchange_code": str(row["exchange_code"]),
                "is_enabled": bool(row.get("is_enabled")),
                "use_public_api": bool(row.get("use_public_api")),
                "api_key": str(row.get("api_key") or ""),
                "api_secret": str(row.get("api_secret") or ""),
                "api_passphrase": str(row.get("api_passphrase") or ""),
                "remark": str(row.get("remark") or ""),
            }
            for row in rows
        }

    def get_config_detail(self, exchange_code: str) -> Dict[str, object] | None:
        row = system_exchange_repository.get_config_by_exchange_code(exchange_code.strip().lower())
        if row is None:
            return None
        return {
            "exchange_code": str(row.get("exchange_code") or ""),
            "exchange_label": EXCHANGE_LABELS.get(
                str(row.get("exchange_code") or ""),
                str(row.get("exchange_code") or "").upper(),
            ),
            "is_enabled": bool(row.get("is_enabled")),
            "use_public_api": bool(row.get("use_public_api")),
            "api_key": str(row.get("api_key") or ""),
            "api_secret": str(row.get("api_secret") or ""),
            "api_passphrase": str(row.get("api_passphrase") or ""),
            "remark": str(row.get("remark") or ""),
            "updated_at": self._format_datetime(row.get("updated_at")),
        }

    def list_swap_symbols(self, exchange_code: str) -> Dict[str, object] | None:
        normalized_exchange_code = str(exchange_code or "").strip().lower()
        if normalized_exchange_code not in EXCHANGE_LABELS:
            return None

        rows = market_repository.list_active_markets(
            exchange_codes=[normalized_exchange_code],
            market_type="swap",
        )
        symbols = sorted(
            {
                str(row.get("symbol") or "").strip()
                for row in rows
                if str(row.get("symbol") or "").strip()
                and is_u_margin_linear_swap_market(row)
            }
        )
        return {
            "exchange_code": normalized_exchange_code,
            "exchange_label": EXCHANGE_LABELS.get(normalized_exchange_code, normalized_exchange_code.upper()),
            "symbols": symbols,
            "symbol_count": len(symbols),
        }

    def refresh_swap_symbols(self, exchange_code: str) -> Dict[str, object] | None:
        normalized_exchange_code = str(exchange_code or "").strip().lower()
        if normalized_exchange_code not in EXCHANGE_LABELS:
            return None

        from app.application.services.market_sync_service import market_sync_service

        result = market_sync_service.sync_exchange_swap_markets_incremental(normalized_exchange_code)
        latest = self.list_swap_symbols(normalized_exchange_code) or {
            "exchange_code": normalized_exchange_code,
            "exchange_label": EXCHANGE_LABELS.get(normalized_exchange_code, normalized_exchange_code.upper()),
            "symbols": [],
            "symbol_count": 0,
        }
        return {
            **latest,
            **result,
        }

    def update_config(
        self,
        payload: SystemExchangeConfigUpdateRequest,
        _: AuthUser,
    ) -> Dict[str, object]:
        exchange_code = str(payload.exchange_code or "").strip().lower()
        if exchange_code not in EXCHANGE_LABELS:
            raise AccountValidationError("系统交易所代码不在支持范围内。")

        try:
            entity = system_exchange_repository.upsert_config(
                exchange_code=exchange_code,
                is_enabled=bool(payload.is_enabled),
                use_public_api=bool(payload.use_public_api),
                api_key=str(payload.api_key or "").strip(),
                api_secret=str(payload.api_secret or "").strip(),
                api_passphrase=str(payload.api_passphrase or "").strip(),
                remark=str(payload.remark or "").strip(),
            )
        except Exception as exc:
            raise AccountPersistenceError("保存系统交易所配置失败：数据库操作异常。") from exc

        feed_status_map = self._build_market_feed_status_map([entity.exchange_code])
        return self._build_row(
            {
                "id": entity.id,
                "exchange_code": entity.exchange_code,
                "is_enabled": entity.is_enabled,
                "use_public_api": entity.use_public_api,
                "api_key": entity.api_key,
                "api_secret": entity.api_secret,
                "api_passphrase": entity.api_passphrase,
                "remark": entity.remark,
                "created_at": entity.created_at,
                "updated_at": entity.updated_at,
            },
            feed_status_map=feed_status_map,
        )

    def build_summary_cards(self, rows: List[Dict[str, object]]) -> List[Dict[str, str]]:
        enabled_count = sum(1 for row in rows if bool(row.get("is_enabled")))
        public_count = sum(1 for row in rows if bool(row.get("use_public_api")))
        private_count = sum(
            1
            for row in rows
            if bool(row.get("is_enabled")) and not bool(row.get("use_public_api"))
        )
        ready_count = sum(1 for row in rows if str(row.get("config_status") or "") == "已配置")

        return [
            {
                "key": "exchange_count",
                "label": "交易所数量",
                "value": str(len(rows)),
                "change": "当前支持的系统级交易所配置",
                "tone": "brand",
            },
            {
                "key": "enabled_count",
                "label": "已启用",
                "value": str(enabled_count),
                "change": "这些交易所会参与系统公共数据同步",
                "tone": "positive",
            },
            {
                "key": "mode_count",
                "label": "私有模式",
                "value": str(private_count),
                "change": f"公开接口 {public_count} / 私有接口 {private_count}",
                "tone": "brand",
            },
            {
                "key": "ready_count",
                "label": "已配置密钥",
                "value": str(ready_count),
                "change": "仅统计已填写系统 API Key/Secret 的交易所",
                "tone": "warning" if ready_count < enabled_count else "positive",
            },
        ]

    def _build_row(
        self,
        row: Dict[str, object],
        *,
        feed_status_map: Dict[str, Dict[str, object]] | None = None,
    ) -> Dict[str, object]:
        exchange_code = str(row.get("exchange_code") or "").strip().lower()
        api_key = str(row.get("api_key") or "")
        api_secret = str(row.get("api_secret") or "")
        api_passphrase = str(row.get("api_passphrase") or "")
        is_enabled = bool(row.get("is_enabled"))
        use_public_api = bool(row.get("use_public_api"))
        has_private_config = bool(api_key and api_secret)
        feed_status = (feed_status_map or {}).get(exchange_code, {})

        if use_public_api:
            mode_label = "公开接口"
            config_status = "公开模式"
            config_tone = "brand"
        elif has_private_config:
            mode_label = "系统私有接口"
            config_status = "已配置"
            config_tone = "positive"
        else:
            mode_label = "系统私有接口"
            config_status = "未配置"
            config_tone = "warning"

        if not is_enabled:
            feed_status_label = "未启用"
            feed_status_tone = "idle"
            feed_status_detail = "当前交易所已关闭"
        else:
            feed_status_label = str(feed_status.get("label") or "未开始")
            feed_status_tone = str(feed_status.get("tone") or "warning")
            feed_status_detail = str(feed_status.get("detail") or "尚未收到永续实时行情")

        return {
            "id": int(row.get("id") or 0),
            "exchange_code": exchange_code,
            "exchange_label": EXCHANGE_LABELS.get(exchange_code, exchange_code.upper()),
            "is_enabled": is_enabled,
            "status_label": "已启用" if is_enabled else "已停用",
            "status_tone": "positive" if is_enabled else "warning",
            "use_public_api": use_public_api,
            "mode_label": mode_label,
            "config_status": config_status,
            "config_tone": config_tone,
            "market_feed_status_label": feed_status_label,
            "market_feed_status_tone": feed_status_tone,
            "market_feed_status_detail": feed_status_detail,
            "api_key": self._mask_secret(api_key, left=4, right=4),
            "api_secret": self._mask_secret(api_secret, left=3, right=3),
            "api_passphrase": "已配置" if api_passphrase else "未配置",
            "remark": str(row.get("remark") or "--"),
            "updated_at": self._format_datetime(row.get("updated_at")),
        }

    def _build_market_feed_status_map(self, exchange_codes: List[str]) -> Dict[str, Dict[str, object]]:
        normalized_codes = [
            str(item or "").strip().lower()
            for item in exchange_codes
            if str(item or "").strip()
        ]
        if not normalized_codes:
            return {}

        market_count_map: Dict[str, int] = defaultdict(int)
        latest_ticker_at_map: Dict[str, datetime] = {}
        recent_ticker_count_map: Dict[str, int] = defaultdict(int)
        stale_before = datetime.now() - timedelta(seconds=MARKET_FEED_STALE_SECONDS)

        market_rows = market_repository.list_active_markets(
            exchange_codes=normalized_codes,
            market_type="swap",
        )
        for row in market_rows:
            exchange_code = str(row.get("exchange_code") or "").strip().lower()
            if not exchange_code:
                continue
            if not is_u_margin_linear_swap_market(row):
                continue
            market_count_map[exchange_code] += 1

        for ticker in market_runtime_cache.list_tickers():
            exchange_code = str(ticker.exchange_code or "").strip().lower()
            if exchange_code not in normalized_codes or str(ticker.market_type or "") != "swap":
                continue
            if ticker.synced_at is None:
                continue
            latest_ticker_at = latest_ticker_at_map.get(exchange_code)
            if latest_ticker_at is None or ticker.synced_at > latest_ticker_at:
                latest_ticker_at_map[exchange_code] = ticker.synced_at
            if ticker.synced_at >= stale_before:
                recent_ticker_count_map[exchange_code] += 1

        result: Dict[str, Dict[str, object]] = {}
        for exchange_code in normalized_codes:
            market_count = int(market_count_map.get(exchange_code) or 0)
            recent_ticker_count = int(recent_ticker_count_map.get(exchange_code) or 0)
            latest_ticker_at = latest_ticker_at_map.get(exchange_code)

            if market_count <= 0:
                result[exchange_code] = {
                    "label": "未同步",
                    "tone": "warning",
                    "detail": "当前没有永续合约市场缓存",
                }
                continue

            if recent_ticker_count > 0:
                result[exchange_code] = {
                    "label": "成功",
                    "tone": "positive",
                    "detail": f"最近 {MARKET_FEED_STALE_SECONDS} 秒内收到 {recent_ticker_count} 个永续行情键",
                }
                continue

            if latest_ticker_at is not None:
                result[exchange_code] = {
                    "label": "中断",
                    "tone": "warning",
                    "detail": f"最近一次推送时间 {self._format_datetime(latest_ticker_at)}",
                }
                continue

            result[exchange_code] = {
                "label": "失败",
                "tone": "negative",
                "detail": "已启用，但尚未收到永续实时行情",
            }

        return result

    def _mask_secret(self, value: str, *, left: int, right: int) -> str:
        if not value:
            return "--"
        if len(value) <= left + right:
            return value
        return f"{value[:left]}...{value[-right:]}"

    def _format_datetime(self, value) -> str:
        if value is None:
            return "--"
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")
        return str(value)


system_exchange_config_service = SystemExchangeConfigService()
