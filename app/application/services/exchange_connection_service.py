"""Exchange service backed by CCXT."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, List

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


@dataclass(frozen=True)
class BalanceSnapshot:
    available_amount: float
    frozen_amount: float
    total_amount: float


@dataclass(frozen=True)
class TradingFeeSnapshot:
    maker_fee_rate: float
    taker_fee_rate: float


@dataclass(frozen=True)
class FundingFeeEntry:
    exchange_record_id: str
    symbol: str
    asset_code: str
    amount: float
    timestamp_ms: int
    raw_payload: Dict[str, Any]


class ExchangeConnectionService:
    """Calls a private exchange API to validate whether submitted credentials work."""

    def __init__(self) -> None:
        self._position_mode_cache: Dict[str, tuple[str, datetime]] = {}
        self._position_mode_lock = RLock()

    def build_exchange_client(self, payload: ExchangeConnectionTestRequest) -> Any:
        normalized = self._normalize_payload(payload)
        self._validate_payload(normalized)
        return self._build_exchange(normalized)

    def build_public_exchange_client(self, *, exchange_code: str, market_type: str) -> Any:
        normalized = {
            "market_type": str(market_type or "").strip().lower(),
            "exchange_code": str(exchange_code or "").strip().lower(),
            "api_key": "",
            "api_secret": "",
            "api_passphrase": "",
        }
        if normalized["market_type"] not in {"spot", "swap"}:
            raise ExchangeValidationError("请选择市场类型。")
        if normalized["exchange_code"] not in EXCHANGE_IDS:
            raise ExchangeValidationError("请选择交易所。")
        return self._build_exchange(normalized)

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
        snapshot = self.fetch_balance_snapshot(payload)
        return float(snapshot.available_amount)

    def fetch_balance_snapshot(self, payload: ExchangeConnectionTestRequest) -> BalanceSnapshot:
        normalized = self._normalize_payload(payload)
        self._validate_payload(normalized)

        exchange = self._build_exchange(normalized)
        try:
            balance = exchange.fetch_balance()
            available_amount = float(
                self._extract_available_balance(
                    balance,
                    normalized["market_type"],
                    normalized["exchange_code"],
                )
            )
            total_amount = float(
                self._extract_total_balance(
                    balance,
                    normalized["market_type"],
                    normalized["exchange_code"],
                )
            )
            frozen_amount = max(total_amount - available_amount, 0.0)
            return BalanceSnapshot(
                available_amount=max(available_amount, 0.0),
                frozen_amount=max(frozen_amount, 0.0),
                total_amount=max(total_amount, available_amount, 0.0),
            )
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

    def fetch_trading_fee_snapshot(self, payload: ExchangeConnectionTestRequest) -> TradingFeeSnapshot:
        normalized = self._normalize_payload(payload)
        self._validate_payload(normalized)

        exchange = self._build_exchange(normalized)
        try:
            maker_fee_rate = 0.05
            taker_fee_rate = 0.05
            fee_payload = None

            try:
                if hasattr(exchange, "fetch_trading_fees") and exchange.has.get("fetchTradingFees"):
                    fee_payload = exchange.fetch_trading_fees()
                elif hasattr(exchange, "fetchTradingFees") and exchange.has.get("fetchTradingFees"):
                    fee_payload = exchange.fetchTradingFees()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Fetch trading fees failed: exchange=%s market_type=%s detail=%s",
                    normalized["exchange_code"],
                    normalized["market_type"],
                    exc,
                )

            parsed = self._extract_trading_fee_snapshot(
                fee_payload,
                exchange_code=normalized["exchange_code"],
                market_type=normalized["market_type"],
            )
            if parsed is not None:
                maker_fee_rate, taker_fee_rate = parsed

            return TradingFeeSnapshot(
                maker_fee_rate=max(float(maker_fee_rate or 0), 0.0),
                taker_fee_rate=max(float(taker_fee_rate or 0), 0.0),
            )
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def fetch_order_book_snapshot(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbol: str,
        limit: int = 20,
    ) -> Dict[str, Any]:
        exchange = self.build_public_exchange_client(exchange_code=exchange_code, market_type=market_type)
        try:
            if hasattr(exchange, "load_markets"):
                try:
                    exchange.load_markets()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Load markets before order book failed: exchange=%s market_type=%s detail=%s",
                        exchange_code,
                        market_type,
                        exc,
                    )
            return exchange.fetch_order_book(str(symbol or ""), limit=max(1, int(limit or 20)))
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def fetch_funding_fee_entries(
        self,
        payload: ExchangeConnectionTestRequest,
        *,
        symbol: str,
        since_ms: int,
        limit: int = 50,
    ) -> List[FundingFeeEntry]:
        normalized = self._normalize_payload(payload)
        self._validate_payload(normalized)

        exchange = self._build_exchange(normalized)
        try:
            if hasattr(exchange, "load_markets"):
                try:
                    exchange.load_markets()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Load markets before funding history failed: exchange=%s market_type=%s detail=%s",
                        normalized["exchange_code"],
                        normalized["market_type"],
                        exc,
                    )

            rows: List[Any] = []
            if hasattr(exchange, "fetch_funding_history") and exchange.has.get("fetchFundingHistory"):
                rows = exchange.fetch_funding_history(str(symbol or ""), since=int(since_ms or 0), limit=max(1, int(limit or 50)))
                return self._normalize_funding_fee_entries(rows, symbol=symbol, funding_history_payload=True)

            if hasattr(exchange, "fetch_ledger") and exchange.has.get("fetchLedger"):
                rows = exchange.fetch_ledger(None, since=int(since_ms or 0), limit=max(1, int(limit or 50)))
                return self._normalize_funding_fee_entries(rows, symbol=symbol, funding_history_payload=False)

            return []
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    def get_position_mode(self, client: Any, payload: ExchangeConnectionTestRequest) -> str:
        normalized = self._normalize_payload(payload)
        if normalized["market_type"] != "swap":
            return "oneway"

        cache_key = self._position_mode_cache_key(payload.account_id, normalized)
        cached_mode = self._read_cached_position_mode(cache_key)
        if cached_mode:
            return cached_mode

        resolved_mode = "unknown"
        try:
            if hasattr(client, "fetch_position_mode"):
                resolved_mode = self._normalize_position_mode(client.fetch_position_mode())
            elif hasattr(client, "fetchPositionMode"):
                resolved_mode = self._normalize_position_mode(client.fetchPositionMode())
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Fetch position mode failed: account_id=%s exchange=%s detail=%s",
                payload.account_id,
                normalized["exchange_code"],
                exc,
            )

        self._write_cached_position_mode(cache_key, resolved_mode)
        return resolved_mode

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
        if payload["exchange_code"] == "okx":
            options["options"]["fetchMarkets"] = {
                "types": ["spot" if payload["market_type"] == "spot" else "swap"]
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

    def _extract_available_balance(self, balance: Any, market_type: str, exchange_code: str) -> float:
        if not isinstance(balance, dict):
            return 0.0

        if market_type == "swap":
            preferred_codes = ("USDT", "USD", "USDC")

            if exchange_code == "binance":
                info = balance.get("info")
                if isinstance(info, dict):
                    assets = info.get("assets")
                    if isinstance(assets, list):
                        for code in preferred_codes:
                            matched = next(
                                (
                                    item
                                    for item in assets
                                    if isinstance(item, dict) and str(item.get("asset") or "").upper() == code
                                ),
                                None,
                            )
                            if matched is None:
                                continue
                            candidate = self._pick_first_numeric(
                                matched,
                                ("maxWithdrawAmount", "availableBalance", "walletBalance", "marginBalance"),
                            )
                            if candidate is not None:
                                return max(candidate, 0.0)

                    candidate = self._pick_first_numeric(
                        info,
                        ("availableBalance", "maxWithdrawAmount"),
                    )
                    if candidate is not None:
                        return max(candidate, 0.0)

                for code in preferred_codes:
                    asset_info = balance.get(code)
                    if not isinstance(asset_info, dict):
                        continue
                    candidate = self._pick_first_numeric(
                        asset_info,
                        ("maxWithdrawAmount", "free", "availableBalance", "walletBalance", "marginBalance"),
                    )
                    if candidate is not None:
                        return max(candidate, 0.0)

            for code in preferred_codes:
                asset_info = balance.get(code)
                if not isinstance(asset_info, dict):
                    continue
                candidate = self._pick_first_numeric(
                    asset_info,
                    ("free", "total", "availableBalance", "maxWithdrawAmount", "walletBalance"),
                )
                if candidate is not None:
                    return max(candidate, 0.0)

            total = 0.0
            for code, asset_info in balance.items():
                if code in {"info", "free", "used", "total", "timestamp", "datetime"}:
                    continue
                if not isinstance(asset_info, dict):
                    continue
                candidate = self._pick_first_numeric(asset_info, ("free", "total"))
                if candidate is None:
                    continue
                total += candidate
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

    def _extract_total_balance(self, balance: Any, market_type: str, exchange_code: str) -> float:
        if not isinstance(balance, dict):
            return 0.0

        if market_type == "swap":
            preferred_codes = ("USDT", "USD", "USDC")

            if exchange_code == "binance":
                info = balance.get("info")
                if isinstance(info, dict):
                    assets = info.get("assets")
                    if isinstance(assets, list):
                        for code in preferred_codes:
                            matched = next(
                                (
                                    item
                                    for item in assets
                                    if isinstance(item, dict) and str(item.get("asset") or "").upper() == code
                                ),
                                None,
                            )
                            if matched is None:
                                continue
                            candidate = self._pick_first_numeric(
                                matched,
                                ("walletBalance", "marginBalance", "availableBalance", "maxWithdrawAmount"),
                            )
                            if candidate is not None:
                                return max(candidate, 0.0)

                for code in preferred_codes:
                    asset_info = balance.get(code)
                    if not isinstance(asset_info, dict):
                        continue
                    candidate = self._pick_first_numeric(
                        asset_info,
                        ("total", "walletBalance", "marginBalance", "free", "availableBalance"),
                    )
                    if candidate is not None:
                        return max(candidate, 0.0)

            for code in preferred_codes:
                asset_info = balance.get(code)
                if not isinstance(asset_info, dict):
                    continue
                candidate = self._pick_first_numeric(
                    asset_info,
                    ("total", "walletBalance", "marginBalance", "free", "availableBalance"),
                )
                if candidate is not None:
                    return max(candidate, 0.0)

            total = 0.0
            for code, asset_info in balance.items():
                if code in {"info", "free", "used", "total", "timestamp", "datetime"}:
                    continue
                if not isinstance(asset_info, dict):
                    continue
                candidate = self._pick_first_numeric(asset_info, ("total", "walletBalance", "marginBalance", "free"))
                if candidate is None:
                    continue
                total += candidate
            return max(total, 0.0)

        total_balances = balance.get("total")
        if isinstance(total_balances, dict):
            preferred_codes = ("USDT", "USD", "USDC")
            for code in preferred_codes:
                candidate = total_balances.get(code)
                if candidate is None:
                    continue
                try:
                    return max(float(candidate or 0), 0.0)
                except (TypeError, ValueError):
                    continue

            total = 0.0
            for candidate in total_balances.values():
                try:
                    total += float(candidate or 0)
                except (TypeError, ValueError):
                    continue
            return max(total, 0.0)

        available_amount = self._extract_available_balance(balance, market_type, exchange_code)
        return max(float(available_amount or 0), 0.0)

    def _pick_first_numeric(self, source: Dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            candidate = source.get(key)
            if candidate is None:
                continue
            try:
                return float(candidate or 0)
            except (TypeError, ValueError):
                continue
        return None

    def _extract_trading_fee_snapshot(
        self,
        payload: Any,
        *,
        exchange_code: str,
        market_type: str,
    ) -> tuple[float, float] | None:
        if payload is None:
            return None

        candidate_rows: list[dict] = []
        if isinstance(payload, dict):
            candidate_rows.append(payload)
            for value in payload.values():
                if isinstance(value, dict):
                    candidate_rows.append(value)
        elif isinstance(payload, list):
            candidate_rows.extend(item for item in payload if isinstance(item, dict))

        best: tuple[float, float] | None = None
        market_hint = "swap" if market_type == "swap" else "spot"

        for row in candidate_rows:
            symbol_text = " ".join(
                str(row.get(key) or "")
                for key in ("symbol", "id", "market", "type")
            ).lower()
            if market_hint == "swap":
                if not any(token in symbol_text for token in ("swap", "future", "perp", "usdt", "linear")) and symbol_text:
                    continue

            maker = self._pick_first_numeric(row, ("maker", "makerFee", "maker_fee", "makerCommission"))
            taker = self._pick_first_numeric(row, ("taker", "takerFee", "taker_fee", "takerCommission"))
            if maker is None and taker is None:
                continue

            maker_percent = abs(float(maker or taker or 0)) * 100
            taker_percent = abs(float(taker or maker or 0)) * 100
            best = (maker_percent, taker_percent)
            if symbol_text:
                break

        return best

    def _normalize_funding_fee_entries(
        self,
        payload: Any,
        *,
        symbol: str,
        funding_history_payload: bool,
    ) -> List[FundingFeeEntry]:
        if not isinstance(payload, list):
            return []

        normalized_symbol = self._normalize_symbol_text(symbol)
        entries: List[FundingFeeEntry] = []
        for index, row in enumerate(payload):
            if not isinstance(row, dict):
                continue
            if not self._is_funding_fee_row(row, funding_history_payload=funding_history_payload):
                continue

            row_symbol = self._normalize_symbol_text(
                row.get("symbol")
                or self._pick_from_info(row, ("symbol", "instId", "contract")),
            )
            if normalized_symbol and row_symbol and normalized_symbol not in row_symbol and row_symbol not in normalized_symbol:
                continue
            if normalized_symbol and not row_symbol and not funding_history_payload:
                continue

            amount = self._pick_first_numeric(
                row,
                ("amount", "fee", "funding", "fundingFee", "income", "change", "balanceChange"),
            )
            if amount is None:
                info = row.get("info")
                if isinstance(info, dict):
                    amount = self._pick_first_numeric(
                        info,
                        ("amount", "fee", "funding", "fundingFee", "income", "change", "balanceChange", "pnl"),
                    )
            if amount is None or float(amount or 0) == 0:
                continue
            timestamp_ms = self._pick_timestamp_ms(row)
            if timestamp_ms <= 0:
                continue
            entries.append(
                FundingFeeEntry(
                    exchange_record_id=str(row.get("id") or self._pick_from_info(row, ("id", "billId", "tranId")) or f"{timestamp_ms}:{index}"),
                    symbol=str(row.get("symbol") or self._pick_from_info(row, ("symbol", "instId", "contract")) or symbol or ""),
                    asset_code=str(row.get("currency") or row.get("code") or self._pick_from_info(row, ("asset", "currency", "coin")) or ""),
                    amount=float(amount or 0),
                    timestamp_ms=timestamp_ms,
                    raw_payload=row,
                )
            )
        return entries

    def _is_funding_fee_row(self, row: Dict[str, Any], *, funding_history_payload: bool) -> bool:
        if funding_history_payload:
            return True
        fields = [
            str(row.get("type") or ""),
            str(row.get("category") or ""),
            str(row.get("description") or ""),
            str(row.get("comment") or ""),
            str(row.get("referenceAccount") or ""),
            str(row.get("direction") or ""),
            str(row.get("info") or ""),
        ]
        haystack = " ".join(fields).lower()
        return "fund" in haystack or "settlement" in haystack or "资金费" in haystack

    def _pick_from_info(self, row: Dict[str, Any], keys: tuple[str, ...]) -> Any:
        info = row.get("info")
        if not isinstance(info, dict):
            return None
        for key in keys:
            value = info.get(key)
            if value not in (None, ""):
                return value
        return None

    def _pick_timestamp_ms(self, row: Dict[str, Any]) -> int:
        for key in ("timestamp", "time", "created", "createdAt"):
            candidate = row.get(key)
            value = self._to_epoch_ms(candidate)
            if value > 0:
                return value
        info = row.get("info")
        if isinstance(info, dict):
            for key in ("time", "timestamp", "uTime", "cTime", "settleTime", "fundingTime", "createdTime"):
                value = self._to_epoch_ms(info.get(key))
                if value > 0:
                    return value
        return 0

    def _to_epoch_ms(self, value: Any) -> int:
        if value in (None, ""):
            return 0
        if isinstance(value, datetime):
            return int(value.timestamp() * 1000)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            text = str(value or "").strip()
            if not text:
                return 0
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return 0
            return int(parsed.timestamp() * 1000)
        if numeric <= 0:
            return 0
        if numeric < 10_000_000_000:
            numeric *= 1000
        return int(numeric)

    def _normalize_symbol_text(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        for token in ("/", ":", "-", "_"):
            text = text.replace(token, "")
        return text

    def _build_connection_error_message(self, error: Exception) -> str:
        return self._map_exchange_error(str(error), prefix="连接测试失败")

    def _build_balance_error_message(self, error: Exception) -> str:
        return self._map_exchange_error(str(error), prefix="读取余额失败")

    def _build_network_error_message(self, error: Exception) -> str:
        return (
            "连接测试失败：交易所接口暂时不可用，或服务器到交易所的网络异常。\n"
            f"原始原因：{self._truncate_message(str(error))}"
        )

    def _position_mode_cache_key(self, account_id: int, payload: Dict[str, str]) -> str:
        return f"{int(account_id or 0)}:{payload['exchange_code']}:{payload['market_type']}"

    def _read_cached_position_mode(self, cache_key: str) -> str:
        with self._position_mode_lock:
            cached = self._position_mode_cache.get(cache_key)
            if cached is None:
                return ""
            mode, expires_at = cached
            if expires_at <= datetime.now():
                self._position_mode_cache.pop(cache_key, None)
                return ""
            return mode

    def _write_cached_position_mode(self, cache_key: str, mode: str) -> None:
        with self._position_mode_lock:
            self._position_mode_cache[cache_key] = (
                str(mode or "unknown"),
                datetime.now() + timedelta(minutes=5),
            )

    def _normalize_position_mode(self, payload: Any) -> str:
        if isinstance(payload, bool):
            return "hedge" if payload else "oneway"

        if isinstance(payload, dict):
            for key in ("hedged", "dualSidePosition", "dualSide", "isHedged"):
                if key not in payload:
                    continue
                return self._normalize_position_mode(payload.get(key))

            for key in ("positionMode", "position_mode", "mode"):
                text = str(payload.get(key) or "").strip().lower()
                if text in {"hedge", "hedged", "long_short_mode"}:
                    return "hedge"
                if text in {"oneway", "one-way", "single", "net_mode"}:
                    return "oneway"

        text = str(payload or "").strip().lower()
        if text in {"true", "1", "hedge", "hedged"}:
            return "hedge"
        if text in {"false", "0", "oneway", "one-way", "single"}:
            return "oneway"
        return "unknown"

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
