"""Manage exchange-specific asset network catalogs for account funding addresses."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import ccxt

from app.application.services.account_support import EXCHANGE_LABELS, NETWORK_LABELS
from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.exchange_connection_service import exchange_connection_service
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import AccountPersistenceError, AccountValidationError


logger = logging.getLogger(__name__)

SUPPORTED_ADDRESS_NETWORK_CODES = {"plasma"}

DEFAULT_ADDRESS_NETWORKS = (
    {"network_code": "TRC20", "network_name": "TRC20", "network_id": "TRC20"},
    {"network_code": "ERC20", "network_name": "ERC20", "network_id": "ERC20"},
    {"network_code": "BEP20", "network_name": "BEP20", "network_id": "BEP20"},
    {"network_code": "ARBITRUM", "network_name": "Arbitrum One", "network_id": "ARBITRUM"},
    {"network_code": "OPTIMISM", "network_name": "Optimism", "network_id": "OPTIMISM"},
    {"network_code": "MATIC", "network_name": "Polygon", "network_id": "MATIC"},
    {"network_code": "PLASMA", "network_name": "Plasma", "network_id": "PLASMA"},
    {"network_code": "SOL", "network_name": "Solana", "network_id": "SOL"},
    {"network_code": "OMNI", "network_name": "OMNI", "network_id": "OMNI"},
    {"network_code": "internal", "network_name": "交易所内部划转", "network_id": "internal"},
)

DEFAULT_NETWORK_CODE_BY_CCXT = {
    "ARBITRUM": "arbitrum",
    "ARBONE": "arbitrum",
    "OP": "optimism",
    "OPTIMISM": "optimism",
    "MATIC": "polygon",
    "POLYGON": "polygon",
    "PLASMA": "plasma",
    "XPL": "plasma",
    "SOL": "solana",
    "SOLANA": "solana",
    "OMNI": "omni",
    "TRC20": "trc20",
    "TRX": "trc20",
    "ERC20": "erc20",
    "ETH": "erc20",
    "BEP20": "bep20",
    "BSC": "bep20",
}

EXCHANGE_CLASS_NAMES = {
    "binance": "binance",
    "bitget": "bitget",
    "okx": "okx",
    "gate": "gate",
    "htx": "htx",
}


class ExchangeAssetNetworkService:
    ASSET_CODE = "USDT"

    def list_network_options(self, exchange_code: str) -> Dict[str, object]:
        normalized_exchange_code = self._normalize_exchange_code(exchange_code)
        rows = account_repository.list_exchange_asset_networks(
            exchange_code=normalized_exchange_code,
            asset_code=self.ASSET_CODE,
        )
        if not rows:
            rows = self._default_rows(normalized_exchange_code)
        rows = self._filter_supported_address_rows(rows)
        return {
            "exchange_code": normalized_exchange_code,
            "exchange_label": EXCHANGE_LABELS.get(normalized_exchange_code, normalized_exchange_code.upper()),
            "asset_code": self.ASSET_CODE,
            "options": rows,
            "option_count": len(rows),
            "updated_at": self._resolve_updated_at(rows),
            "source": "catalog" if rows and rows != self._default_rows(normalized_exchange_code) else "fallback",
        }

    def refresh_network_options(
        self,
        exchange_code: str,
        *,
        market_type: str = "spot",
        api_key: str = "",
        api_secret: str = "",
        api_passphrase: str = "",
    ) -> Dict[str, object]:
        normalized_exchange_code = self._normalize_exchange_code(exchange_code)
        rows = self._fetch_exchange_rows(
            normalized_exchange_code,
            market_type=market_type,
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase,
        )
        if not self._has_external_rows(rows):
            raise AccountValidationError(f"{EXCHANGE_LABELS.get(normalized_exchange_code, normalized_exchange_code.upper())} 暂未返回可用的 USDT 网络。")
        try:
            account_repository.replace_exchange_asset_networks(
                exchange_code=normalized_exchange_code,
                asset_code=self.ASSET_CODE,
                networks=rows,
            )
        except Exception as exc:
            raise AccountPersistenceError("更新交易所网络失败：写入数据库时出错。") from exc
        payload = self.list_network_options(normalized_exchange_code)
        payload["source"] = "remote"
        return payload

    def _fetch_exchange_rows(
        self,
        exchange_code: str,
        *,
        market_type: str = "spot",
        api_key: str = "",
        api_secret: str = "",
        api_passphrase: str = "",
    ) -> List[Dict[str, object]]:
        exchange_class_name = EXCHANGE_CLASS_NAMES.get(exchange_code)
        if not exchange_class_name:
            raise AccountValidationError("交易所不在支持范围内。")
        normalized_market_type = str(market_type or "spot").strip().lower() or "spot"
        use_private_client = self._should_use_private_currency_fetch(
            exchange_code=exchange_code,
            api_key=api_key,
            api_secret=api_secret,
        )
        if use_private_client:
            client = exchange_connection_service.build_exchange_client(
                ExchangeConnectionTestRequest(
                    account_id=0,
                    market_type=normalized_market_type,
                    exchange_code=exchange_code,
                    api_key=str(api_key or "").strip(),
                    api_secret=str(api_secret or "").strip(),
                    api_passphrase=str(api_passphrase or "").strip(),
                )
            )
        else:
            exchange_class = getattr(ccxt, exchange_class_name)
            client = exchange_class(
                {
                    "enableRateLimit": True,
                    "timeout": 10000,
                }
            )
        try:
            try:
                client.session.trust_env = False
            except Exception:
                pass
            currencies = client.fetch_currencies()
            asset = currencies.get(self.ASSET_CODE) or {}
            networks = asset.get("networks") or {}
            rows: List[Dict[str, object]] = []
            seen_codes: set[str] = set()
            for raw_network_code, raw_network in networks.items():
                parsed = self._parse_network_row(raw_network_code, raw_network)
                if parsed is None:
                    continue
                if parsed["network_code"] in seen_codes:
                    continue
                seen_codes.add(parsed["network_code"])
                rows.append(parsed)
            rows.sort(key=lambda item: (item["network_code"] == "internal", str(item["network_name"] or "").lower()))
            rows.append(self._build_internal_row())
            return rows
        except ccxt.NetworkError as exc:
            logger.warning("Refresh exchange asset networks network failed: exchange=%s detail=%s", exchange_code, exc)
            raise AccountValidationError(f"更新 {EXCHANGE_LABELS.get(exchange_code, exchange_code.upper())} 网络失败：交易所接口暂时不可用。") from exc
        except ccxt.ExchangeError as exc:
            logger.warning("Refresh exchange asset networks exchange failed: exchange=%s detail=%s", exchange_code, exc)
            raise AccountValidationError(f"更新 {EXCHANGE_LABELS.get(exchange_code, exchange_code.upper())} 网络失败：{str(exc).strip() or '交易所返回异常'}") from exc
        except Exception as exc:
            logger.exception("Refresh exchange asset networks unexpected failed: exchange=%s", exchange_code)
            raise AccountValidationError("更新交易所网络失败：服务内部异常，请稍后重试。") from exc
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _parse_network_row(self, raw_network_code: str, raw_network: Any) -> Dict[str, object] | None:
        if not isinstance(raw_network, dict):
            return None
        ccxt_network_code = str(raw_network.get("network") or raw_network_code or "").strip()
        if not ccxt_network_code:
            return None
        normalized_label_key = self._normalize_network_code(ccxt_network_code)
        normalized_network_code = str(normalized_label_key or ccxt_network_code).strip()
        network_name = NETWORK_LABELS.get(normalized_label_key, ccxt_network_code)
        network_id = str(raw_network.get("id") or ccxt_network_code).strip()
        return {
            "network_code": normalized_network_code,
            "network_name": network_name,
            "network_id": network_id,
            "is_deposit_enabled": bool(raw_network.get("deposit", True)),
            "is_withdraw_enabled": bool(raw_network.get("withdraw", True)),
        }

    def _default_rows(self, exchange_code: str) -> List[Dict[str, object]]:
        _ = exchange_code
        return self._filter_supported_address_rows(
            [
                {
                    "network_code": str(item["network_code"]),
                    "network_name": str(item["network_name"]),
                    "network_id": str(item["network_id"]),
                    "is_deposit_enabled": True,
                    "is_withdraw_enabled": True,
                }
                for item in DEFAULT_ADDRESS_NETWORKS
            ]
        )

    def _filter_supported_address_rows(self, rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
        filtered_rows: List[Dict[str, object]] = []
        seen_codes: set[str] = set()
        for row in rows:
            normalized_code = self._normalize_network_code(str(row.get("network_code") or "").strip())
            if normalized_code not in SUPPORTED_ADDRESS_NETWORK_CODES:
                continue
            if normalized_code in seen_codes:
                continue
            seen_codes.add(normalized_code)
            filtered_rows.append(
                {
                    "network_code": normalized_code.upper(),
                    "network_name": NETWORK_LABELS.get(normalized_code, str(row.get("network_name") or "").strip() or normalized_code.upper()),
                    "network_id": str(row.get("network_id") or "").strip() or normalized_code.upper(),
                    "is_deposit_enabled": bool(row.get("is_deposit_enabled", True)),
                    "is_withdraw_enabled": bool(row.get("is_withdraw_enabled", True)),
                    "updated_at": row.get("updated_at"),
                    "created_at": row.get("created_at"),
                }
            )
        return filtered_rows

    def _build_internal_row(self) -> Dict[str, object]:
        return {
            "network_code": "internal",
            "network_name": "交易所内部划转",
            "network_id": "internal",
            "is_deposit_enabled": True,
            "is_withdraw_enabled": True,
        }

    def _resolve_updated_at(self, rows: List[Dict[str, object]]) -> str:
        for row in rows:
            updated_at = row.get("updated_at")
            if updated_at:
                return str(updated_at)
        return ""

    def _has_external_rows(self, rows: List[Dict[str, object]]) -> bool:
        return any(str(row.get("network_code") or "").strip().lower() != "internal" for row in rows)

    def _should_use_private_currency_fetch(self, *, exchange_code: str, api_key: str, api_secret: str) -> bool:
        normalized_exchange_code = str(exchange_code or "").strip().lower()
        if normalized_exchange_code not in {"binance", "okx"}:
            return False
        return bool(str(api_key or "").strip() and str(api_secret or "").strip())

    def _normalize_exchange_code(self, exchange_code: str) -> str:
        normalized = str(exchange_code or "").strip().lower()
        if normalized not in EXCHANGE_LABELS:
            raise AccountValidationError("交易所不在支持范围内。")
        return normalized

    def _normalize_network_code(self, network_code: str) -> str:
        normalized = str(network_code or "").strip().upper()
        return DEFAULT_NETWORK_CODE_BY_CCXT.get(normalized, normalized.lower())


exchange_asset_network_service = ExchangeAssetNetworkService()

__all__ = [
    "ExchangeAssetNetworkService",
    "exchange_asset_network_service",
]
