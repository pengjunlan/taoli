"""Exchange service backed by CCXT."""

from __future__ import annotations

from typing import Any, Dict

import ccxt

from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.shared.exceptions import ExchangeConnectionError, ExchangeValidationError


EXCHANGE_IDS = {
    "binance": "binance",
    "bitget": "bitget",
    "okx": "okx",
    "gate": "gate",
    "htx": "htx",
}


class ExchangeConnectionService:
    """Calls a private exchange API to validate whether submitted credentials work."""

    def test_connection(self, payload: ExchangeConnectionTestRequest) -> None:
        normalized = self._normalize_payload(payload)
        self._validate_payload(normalized)

        exchange = self._build_exchange(normalized)
        try:
            exchange.fetch_balance()
        except (ccxt.AuthenticationError, ccxt.PermissionDenied) as exc:
            raise ExchangeConnectionError("连接失败，请检查 API Key、Secret、Passphrase 或接口权限。") from exc
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError("连接失败，交易所接口暂时不可用或网络异常。") from exc
        except ccxt.ExchangeError as exc:
            raise ExchangeConnectionError(self._map_exchange_error(str(exc))) from exc
        except Exception as exc:
            raise ExchangeConnectionError("连接失败，请稍后重试。") from exc
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def fetch_available_balance(self, payload: ExchangeConnectionTestRequest) -> float:
        normalized = self._normalize_payload(payload)
        self._validate_payload(normalized)

        exchange = self._build_exchange(normalized)
        try:
            balance = exchange.fetch_balance()
            return float(self._extract_available_balance(balance, normalized["market_type"]))
        except (ccxt.AuthenticationError, ccxt.PermissionDenied) as exc:
            raise ExchangeConnectionError("读取余额失败，请检查 API Key、Secret、Passphrase 或接口权限。") from exc
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError("读取余额失败，交易所接口暂时不可用或网络异常。") from exc
        except ccxt.ExchangeError as exc:
            raise ExchangeConnectionError(self._map_exchange_error(str(exc)).replace("连接失败", "读取余额失败")) from exc
        except Exception as exc:
            raise ExchangeConnectionError("读取余额失败，请稍后重试。") from exc
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def _normalize_payload(self, payload: ExchangeConnectionTestRequest) -> Dict[str, str]:
        return {
            "market_type": payload.market_type.strip().lower(),
            "exchange_code": payload.exchange_code.strip().lower(),
            "api_key": payload.api_key.strip(),
            "api_secret": payload.api_secret.strip(),
            "api_passphrase": payload.api_passphrase.strip(),
        }

    def _validate_payload(self, payload: Dict[str, str]) -> None:
        if payload["market_type"] not in {"spot", "swap"}:
            raise ExchangeValidationError("请选择市场类型。")
        if payload["exchange_code"] not in EXCHANGE_IDS:
            raise ExchangeValidationError("请选择交易所。")
        if not payload["api_key"]:
            raise ExchangeValidationError("API Key 为必填项。")
        if not payload["api_secret"]:
            raise ExchangeValidationError("API Secret 为必填项。")
        if payload["exchange_code"] == "okx" and not payload["api_passphrase"]:
            raise ExchangeValidationError("OKX 需要填写 API Passphrase。")

    def _build_exchange(self, payload: Dict[str, str]) -> Any:
        exchange_class = getattr(ccxt, EXCHANGE_IDS[payload["exchange_code"]])
        options: Dict[str, Any] = {
            "apiKey": payload["api_key"],
            "secret": payload["api_secret"],
            "enableRateLimit": True,
            "timeout": 10000,
            "options": {
                "defaultType": "spot" if payload["market_type"] == "spot" else "swap",
            },
        }
        if payload["api_passphrase"]:
            options["password"] = payload["api_passphrase"]

        return exchange_class(options)

    def _extract_available_balance(self, balance: Any, market_type: str) -> float:
        if not isinstance(balance, dict):
            return 0.0

        total = 0.0
        if market_type == "swap":
            for code, asset_info in balance.items():
                if code in {"info", "free", "used", "total", "timestamp", "datetime"}:
                    continue
                if not isinstance(asset_info, dict):
                    continue
                candidate = asset_info.get("free")
                if candidate is None:
                    candidate = asset_info.get("total")
                if candidate is None:
                    continue
                try:
                    total += float(candidate or 0)
                except (TypeError, ValueError):
                    continue
            return max(total, 0.0)

        free_balances = balance.get("free")
        if isinstance(free_balances, dict):
            preferred_codes = ("USDT", "USD", "USDC")
            for code in preferred_codes:
                candidate = free_balances.get(code)
                if candidate is None:
                    continue
                try:
                    return max(float(candidate or 0), 0.0)
                except (TypeError, ValueError):
                    continue

            total = 0.0
            for candidate in free_balances.values():
                try:
                    total += float(candidate or 0)
                except (TypeError, ValueError):
                    continue
            return max(total, 0.0)

        return 0.0

    def _map_exchange_error(self, message: str) -> str:
        lowered = message.lower()
        if "api-key" in lowered or "api key" in lowered or "signature" in lowered or "passphrase" in lowered:
            return "连接失败，请检查 API Key、Secret 或 Passphrase。"
        if "permission" in lowered or "forbidden" in lowered:
            return "连接失败，当前 API 权限不足。"
        return "连接失败，请检查密钥配置是否正确。"


exchange_connection_service = ExchangeConnectionService()
