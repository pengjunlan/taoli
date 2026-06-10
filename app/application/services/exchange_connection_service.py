"""Exchange service backed by CCXT."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


class ExchangeConnectionService:
    """Calls a private exchange API to validate whether submitted credentials work."""

    def test_connection(self, payload: ExchangeConnectionTestRequest) -> None:
        normalized = self._normalize_payload(payload)
        self._validate_payload(normalized)

        exchange = self._build_exchange(normalized)
        try:
            exchange.fetch_balance()
        except (ccxt.AuthenticationError, ccxt.PermissionDenied) as exc:
            logger.warning(
                "Exchange connection auth failed: exchange=%s market_type=%s detail=%s",
                normalized["exchange_code"],
                normalized["market_type"],
                exc,
            )
            raise ExchangeConnectionError(self._build_connection_error_message(exc)) from exc
        except ccxt.NetworkError as exc:
            logger.warning(
                "Exchange connection network failed: exchange=%s market_type=%s detail=%s",
                normalized["exchange_code"],
                normalized["market_type"],
                exc,
            )
            raise ExchangeConnectionError(self._build_network_error_message(exc)) from exc
        except ccxt.ExchangeError as exc:
            logger.warning(
                "Exchange connection exchange error: exchange=%s market_type=%s detail=%s",
                normalized["exchange_code"],
                normalized["market_type"],
                exc,
            )
            raise ExchangeConnectionError(self._build_connection_error_message(exc)) from exc
        except Exception as exc:
            logger.exception(
                "Exchange connection unexpected error: exchange=%s market_type=%s",
                normalized["exchange_code"],
                normalized["market_type"],
            )
            raise ExchangeConnectionError(
                "连接测试失败：交易所返回了未预期的异常。\n"
                f"原始原因：{self._truncate_message(str(exc))}"
            ) from exc
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
            logger.warning(
                "Fetch balance auth failed: exchange=%s market_type=%s detail=%s",
                normalized["exchange_code"],
                normalized["market_type"],
                exc,
            )
            raise ExchangeConnectionError(self._build_balance_error_message(exc)) from exc
        except ccxt.NetworkError as exc:
            logger.warning(
                "Fetch balance network failed: exchange=%s market_type=%s detail=%s",
                normalized["exchange_code"],
                normalized["market_type"],
                exc,
            )
            raise ExchangeConnectionError(
                "读取余额失败：交易所接口暂时不可用，或服务器到交易所的网络异常。\n"
                f"原始原因：{self._truncate_message(str(exc))}"
            ) from exc
        except ccxt.ExchangeError as exc:
            logger.warning(
                "Fetch balance exchange error: exchange=%s market_type=%s detail=%s",
                normalized["exchange_code"],
                normalized["market_type"],
                exc,
            )
            raise ExchangeConnectionError(self._build_balance_error_message(exc)) from exc
        except Exception as exc:
            logger.exception(
                "Fetch balance unexpected error: exchange=%s market_type=%s",
                normalized["exchange_code"],
                normalized["market_type"],
            )
            raise ExchangeConnectionError(
                "读取余额失败：交易所返回了未预期的异常。\n"
                f"原始原因：{self._truncate_message(str(exc))}"
            ) from exc
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
        exchange_class_name = self._resolve_exchange_class_name(payload["exchange_code"], payload["market_type"])
        exchange_class = getattr(ccxt, exchange_class_name)
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

        exchange = exchange_class(options)
        try:
            exchange.session.trust_env = False
        except Exception:
            pass
        return exchange

    def _resolve_exchange_class_name(self, exchange_code: str, market_type: str) -> str:
        if exchange_code == "binance" and market_type == "swap":
            return "binanceusdm"
        return EXCHANGE_IDS[exchange_code]

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

    def _build_connection_error_message(self, error: Exception) -> str:
        return self._map_exchange_error(str(error), prefix="连接测试失败")

    def _build_balance_error_message(self, error: Exception) -> str:
        return self._map_exchange_error(str(error), prefix="读取余额失败")

    def _build_network_error_message(self, error: Exception) -> str:
        return (
            "连接测试失败：交易所接口暂时不可用，或服务器到交易所的网络异常。\n"
            f"原始原因：{self._truncate_message(str(error))}"
        )

    def _map_exchange_error(self, message: str, *, prefix: str) -> str:
        lowered = message.lower()
        raw_message = self._truncate_message(message)

        if "signature for this request is not valid" in lowered or "code\":-1022" in lowered or "signature" in lowered:
            return (
                f"{prefix}：Binance 返回签名无效（code -1022）。\n"
                "请重点检查 API Secret 是否填写正确，并确认 API Key 和 Secret 是同一套。\n"
                f"原始原因：{raw_message}"
            )
        if "invalid api-key" in lowered or "invalid api key" in lowered or "api-key format invalid" in lowered:
            return (
                f"{prefix}：API Key 无效、已被禁用，或填错了账号。\n"
                f"原始原因：{raw_message}"
            )
        if "passphrase" in lowered:
            return (
                f"{prefix}：Passphrase 不正确或缺失。\n"
                f"原始原因：{raw_message}"
            )
        if "permission" in lowered or "forbidden" in lowered:
            return (
                f"{prefix}：API 权限不足。\n"
                "请检查是否开启了读取资产/合约权限，并确认该 Key 是否允许当前操作。\n"
                f"原始原因：{raw_message}"
            )
        if ("ip" in lowered and "whitelist" in lowered) or "restricted ip" in lowered:
            return (
                f"{prefix}：当前服务器 IP 不在交易所 API 白名单内。\n"
                "请把服务器 IP 加到该 API 的白名单后再试。\n"
                f"原始原因：{raw_message}"
            )
        if "timestamp" in lowered or "recvwindow" in lowered or "\"code\":-1021" in lowered:
            return (
                f"{prefix}：交易所时间校验失败。\n"
                "请检查服务器时间是否准确，或适当放宽交易所 API 的时间窗口设置。\n"
                f"原始原因：{raw_message}"
            )
        return (
            f"{prefix}：请检查密钥配置是否正确。\n"
            f"原始原因：{raw_message}"
        )

    def _truncate_message(self, message: str, max_length: int = 220) -> str:
        text = " ".join(str(message or "").split())
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 3]}..."


exchange_connection_service = ExchangeConnectionService()
