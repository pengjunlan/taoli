"""Public market synchronization and pair generation service."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List

import ccxt

from app.application.services.swap_market_rules import is_u_margin_linear_swap_market
from app.infrastructure.persistence.market_repository import market_repository
from app.application.services.system_exchange_config_service import system_exchange_config_service


logger = logging.getLogger(__name__)


SUPPORTED_MARKET_TYPES = ("swap",)


class MarketSyncService:
    def list_supported_exchange_codes(self) -> List[str]:
        config_map = system_exchange_config_service.get_config_map()
        if not config_map:
            return ["binance", "bitget", "okx", "gate", "htx"]
        return [
            exchange_code
            for exchange_code, row in config_map.items()
            if bool(row.get("is_enabled"))
        ]

    def sync_all_public_markets(self, exchange_codes: Iterable[str] | None = None) -> Dict[str, int]:
        codes = list(exchange_codes or self.list_supported_exchange_codes())
        synced_market_count = 0
        generated_funding_pairs = 0
        generated_spread_pairs = 0

        for exchange_code in codes:
            for market_type in SUPPORTED_MARKET_TYPES:
                try:
                    rows = self._fetch_exchange_markets(exchange_code=exchange_code, market_type=market_type)
                    market_repository.replace_markets(
                        exchange_code=exchange_code,
                        market_type=market_type,
                        rows=rows,
                    )
                    synced_market_count += len(rows)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Sync public markets failed for exchange=%s market_type=%s: %s",
                        exchange_code,
                        market_type,
                        exc,
                    )

        funding_pairs = self._build_funding_pairs()
        spread_pairs = self._build_spread_pairs()
        market_repository.replace_pairs(pair_type="funding", rows=funding_pairs)
        market_repository.replace_pairs(pair_type="spread", rows=spread_pairs)
        generated_funding_pairs = len(funding_pairs)
        generated_spread_pairs = len(spread_pairs)

        return {
            "market_count": synced_market_count,
            "funding_pair_count": generated_funding_pairs,
            "spread_pair_count": generated_spread_pairs,
        }

    def sync_exchange_swap_markets_incremental(self, exchange_code: str) -> Dict[str, int]:
        normalized_exchange_code = str(exchange_code or "").strip().lower()
        if not normalized_exchange_code:
            raise ValueError("exchange_code is required")

        rows = self._fetch_exchange_markets(
            exchange_code=normalized_exchange_code,
            market_type="swap",
        )
        if not rows:
            raise ValueError(f"{normalized_exchange_code} 未获取到任何永续交易对")

        market_result = market_repository.sync_markets_incremental(
            exchange_code=normalized_exchange_code,
            market_type="swap",
            rows=rows,
        )

        funding_pairs = self._build_funding_pairs()
        spread_pairs = self._build_spread_pairs()
        market_repository.replace_pairs(pair_type="funding", rows=funding_pairs)
        market_repository.replace_pairs(pair_type="spread", rows=spread_pairs)

        return {
            "exchange_code": normalized_exchange_code,
            "fetched_count": len(rows),
            "added_count": int(market_result.get("added_count") or 0),
            "reactivated_count": int(market_result.get("reactivated_count") or 0),
            "marked_inactive_count": int(market_result.get("marked_inactive_count") or 0),
            "funding_pair_count": len(funding_pairs),
            "spread_pair_count": len(spread_pairs),
        }

    def _fetch_exchange_markets(self, *, exchange_code: str, market_type: str) -> List[Dict[str, Any]]:
        exchange = self._build_public_exchange(exchange_code=exchange_code, market_type=market_type)
        try:
            markets = exchange.load_markets()
            synced_at = datetime.now()
            rows: List[Dict[str, Any]] = []
            for market in markets.values():
                if not self._is_market_supported(market=market, market_type=market_type):
                    continue

                base_asset = str(market.get("base") or "").upper()
                quote_asset = str(market.get("quote") or "").upper()
                settle_asset = str(market.get("settle") or quote_asset or "").upper()
                normalized_symbol = self._normalize_symbol(base_asset, quote_asset)

                rows.append(
                    {
                        "symbol": str(market.get("symbol") or ""),
                        "symbol_normalized": normalized_symbol,
                        "base_asset": base_asset,
                        "quote_asset": quote_asset,
                        "settle_asset": settle_asset,
                        "is_contract": bool(market.get("contract")),
                        "is_linear": bool(market.get("linear")),
                        "contract_size": float(market.get("contractSize") or 0),
                        "price_precision": float((market.get("precision") or {}).get("price") or 0),
                        "amount_precision": float((market.get("precision") or {}).get("amount") or 0),
                        "min_amount": float(((market.get("limits") or {}).get("amount") or {}).get("min") or 0),
                        "supports_funding": bool(market.get("swap") or market.get("future") or False),
                        "supports_ws": True,
                        "synced_at": synced_at,
                    }
                )
            return rows
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def _build_public_exchange(self, *, exchange_code: str, market_type: str):
        exchange_class_name = self._resolve_exchange_class_name(exchange_code=exchange_code, market_type=market_type)
        exchange_class = getattr(ccxt, exchange_class_name)
        options = {
            "enableRateLimit": True,
            "timeout": 20000,
            "options": {
                "defaultType": self._resolve_default_type(exchange_code=exchange_code, market_type=market_type),
            },
        }
        if exchange_code == "okx":
            options["options"]["fetchMarkets"] = {"types": [self._resolve_okx_market_fetch_type(market_type)]}

        exchange = exchange_class(options)
        try:
            exchange.session.trust_env = False
        except Exception:
            pass
        return exchange

    def _resolve_exchange_class_name(self, *, exchange_code: str, market_type: str) -> str:
        if exchange_code == "binance" and market_type == "swap":
            return "binanceusdm"
        return exchange_code

    def _resolve_default_type(self, *, exchange_code: str, market_type: str) -> str:
        if exchange_code == "binance" and market_type == "swap":
            return "swap"
        return market_type

    def _resolve_okx_market_fetch_type(self, market_type: str) -> str:
        if market_type == "swap":
            return "swap"
        return "spot"

    def _build_funding_pairs(self) -> List[Dict[str, Any]]:
        enabled_exchange_codes = set(self.list_supported_exchange_codes())
        rows = [
            row
            for row in market_repository.list_active_markets(market_type="swap")
            if str(row.get("exchange_code") or "") in enabled_exchange_codes
            and self._is_opportunity_supported_swap_market(row)
        ]
        grouped: Dict[tuple[str, str, str], List[Dict[str, Any]]] = {}
        for row in rows:
            if not bool(row.get("supports_funding")):
                continue
            symbol_key = str(row.get("symbol_normalized") or "")
            settle_asset = str(row.get("settle_asset") or "").upper()
            contract_type = "linear" if bool(row.get("is_linear")) else "inverse"
            if not symbol_key or not settle_asset:
                continue
            key = (symbol_key, settle_asset, contract_type)
            grouped.setdefault(key, []).append(row)

        generated_at = datetime.now()
        pairs: List[Dict[str, Any]] = []
        for (symbol_key, _settle_asset, _contract_type), items in grouped.items():
            ordered = sorted(items, key=lambda item: str(item.get("exchange_code") or ""))
            for left_index in range(len(ordered)):
                for right_index in range(left_index + 1, len(ordered)):
                    left = ordered[left_index]
                    right = ordered[right_index]
                    pair_key = f"funding:{left['exchange_code']}:{right['exchange_code']}:{symbol_key}"
                    pairs.append(
                        {
                            "pair_key": pair_key,
                            "left_exchange_code": left["exchange_code"],
                            "right_exchange_code": right["exchange_code"],
                            "left_market_type": left["market_type"],
                            "right_market_type": right["market_type"],
                            "symbol_normalized": symbol_key,
                            "left_symbol": left["symbol"],
                            "right_symbol": right["symbol"],
                            "base_asset": left["base_asset"],
                            "quote_asset": left["quote_asset"],
                            "settle_asset": left["settle_asset"],
                            "match_mode": "auto",
                            "pair_reason": "同标的 + 同报价币 + 同类永续",
                            "generated_at": generated_at,
                        }
                    )
        return pairs

    def _build_spread_pairs(self) -> List[Dict[str, Any]]:
        # User-confirmed rule: spread arbitrage only supports perpetual-perpetual pairs.
        enabled_exchange_codes = set(self.list_supported_exchange_codes())
        rows = [
            row
            for row in market_repository.list_active_markets(market_type="swap")
            if str(row.get("exchange_code") or "") in enabled_exchange_codes
            and self._is_opportunity_supported_swap_market(row)
        ]
        grouped: Dict[tuple[str, str, str], List[Dict[str, Any]]] = {}
        for row in rows:
            symbol_key = str(row.get("symbol_normalized") or "")
            settle_asset = str(row.get("settle_asset") or "").upper()
            contract_type = "linear" if bool(row.get("is_linear")) else "inverse"
            if not symbol_key or not settle_asset:
                continue
            key = (symbol_key, settle_asset, contract_type)
            grouped.setdefault(key, []).append(row)

        generated_at = datetime.now()
        pairs: List[Dict[str, Any]] = []
        for (symbol_key, _settle_asset, _contract_type), items in grouped.items():
            ordered = sorted(items, key=lambda item: str(item.get("exchange_code") or ""))
            for left_index in range(len(ordered)):
                for right_index in range(left_index + 1, len(ordered)):
                    left = ordered[left_index]
                    right = ordered[right_index]
                    pair_key = f"spread:swap:{left['exchange_code']}:{right['exchange_code']}:{symbol_key}"
                    pairs.append(
                        {
                            "pair_key": pair_key,
                            "left_exchange_code": left["exchange_code"],
                            "right_exchange_code": right["exchange_code"],
                            "left_market_type": "swap",
                            "right_market_type": "swap",
                            "symbol_normalized": symbol_key,
                            "left_symbol": left["symbol"],
                            "right_symbol": right["symbol"],
                            "base_asset": left["base_asset"],
                            "quote_asset": left["quote_asset"],
                            "settle_asset": left["settle_asset"],
                            "match_mode": "auto",
                            "pair_reason": "同标的 + 同报价币 + 同类市场",
                            "generated_at": generated_at,
                        }
                    )
        return pairs

    def _is_market_supported(self, *, market: Dict[str, Any], market_type: str) -> bool:
        if not bool(market.get("active", True)):
            return False

        if market_type == "spot":
            return bool(market.get("spot"))

        if market_type == "swap":
            return is_u_margin_linear_swap_market(
                {
                    "market_type": market_type,
                    "quote": market.get("quote"),
                    "settle": market.get("settle"),
                    "linear": market.get("linear"),
                }
            )

        return False

    def _is_opportunity_supported_swap_market(self, row: Dict[str, Any]) -> bool:
        return is_u_margin_linear_swap_market(row)

    def _normalize_symbol(self, base_asset: str, quote_asset: str) -> str:
        base = self._normalize_asset_code(base_asset)
        quote = self._normalize_asset_code(quote_asset)
        return f"{base}/{quote}"

    def _normalize_asset_code(self, value: str) -> str:
        asset = str(value or "").upper().strip()
        aliases = {
            "XBT": "BTC",
        }
        return aliases.get(asset, asset)


market_sync_service = MarketSyncService()
