"""Order-book execution quality checks shared by strategy display and execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from threading import RLock
from typing import Any, Dict, List

from app.application.services.exchange_connection_service import exchange_connection_service
from app.application.services.strategy_risk_config import strategy_risk_config
from app.application.services.strategy_rule_runtime_service import StrategyRuleRuntimeView
from app.infrastructure.persistence.market_repository import market_repository


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DepthCheckResult:
    is_supported: bool
    is_ok: bool
    blocked_reason: str = ""
    slippage_percent: float = 0.0
    depth_value_usdt: float = 0.0


class StrategyExecutionQualityService:
    def __init__(self) -> None:
        self._order_book_cache: Dict[str, tuple[datetime, Dict[str, Any] | None]] = {}
        self._order_book_lock = RLock()
        self._order_book_ttl_seconds = 8

    def evaluate_depth_and_slippage(
        self,
        *,
        row: Dict[str, Any],
        runtime_rule: StrategyRuleRuntimeView,
    ) -> tuple[str, float]:
        order_amount = float(runtime_rule.order_amount_usdt or 0)
        if order_amount <= 0:
            return "order_amount_invalid", 0.0

        left_result = self._evaluate_leg(
            exchange_code=str(row.get("left_exchange_code") or ""),
            market_type=str(row.get("left_market_type") or "swap"),
            symbol=str(row.get("left_symbol_raw") or row.get("left_symbol") or ""),
            side="buy",
            order_amount_usdt=order_amount,
            fallback_price=self._parse_float(row.get("left_price_value")),
            leg_name="left",
        )
        if left_result.is_supported and not left_result.is_ok:
            return left_result.blocked_reason, left_result.slippage_percent

        right_result = self._evaluate_leg(
            exchange_code=str(row.get("right_exchange_code") or ""),
            market_type=str(row.get("right_market_type") or "swap"),
            symbol=str(row.get("right_symbol_raw") or row.get("right_symbol") or ""),
            side="sell",
            order_amount_usdt=order_amount,
            fallback_price=self._parse_float(row.get("right_price_value")),
            leg_name="right",
        )
        if right_result.is_supported and not right_result.is_ok:
            return right_result.blocked_reason, left_result.slippage_percent + right_result.slippage_percent

        total_slippage = max(0.0, left_result.slippage_percent) + max(0.0, right_result.slippage_percent)
        return "", total_slippage

    def _evaluate_leg(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbol: str,
        side: str,
        order_amount_usdt: float,
        fallback_price: float,
        leg_name: str,
    ) -> DepthCheckResult:
        if not exchange_code or not market_type or not symbol:
            return DepthCheckResult(False, True)

        order_book = self._fetch_order_book_cached(
            exchange_code=exchange_code,
            market_type=market_type,
            symbol=symbol,
        )
        if not isinstance(order_book, dict):
            return DepthCheckResult(False, True)

        levels = order_book.get("asks" if side == "buy" else "bids")
        if not isinstance(levels, list) or not levels:
            return DepthCheckResult(False, True)

        estimate = self._estimate_fill(
            levels=levels,
            order_amount_usdt=order_amount_usdt,
            exchange_code=exchange_code,
            market_type=market_type,
            symbol=symbol,
        )
        if estimate["filled_value_usdt"] + 1e-9 < order_amount_usdt:
            return DepthCheckResult(
                True,
                False,
                blocked_reason=f"{leg_name}_depth_insufficient",
                depth_value_usdt=estimate["filled_value_usdt"],
            )

        reference_price = fallback_price if fallback_price > 0 else estimate["best_price"]
        slippage = self._calc_slippage_percent(
            side=side,
            reference_price=reference_price,
            average_price=estimate["average_price"],
        )
        max_slippage = max(0.0, float(strategy_risk_config.max_order_book_slippage_percent or 0))
        if max_slippage > 0 and slippage > max_slippage:
            return DepthCheckResult(
                True,
                False,
                blocked_reason=f"{leg_name}_slippage_too_large",
                slippage_percent=slippage,
                depth_value_usdt=estimate["filled_value_usdt"],
            )

        return DepthCheckResult(
            True,
            True,
            slippage_percent=slippage,
            depth_value_usdt=estimate["filled_value_usdt"],
        )

    def _fetch_order_book_cached(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbol: str,
    ) -> Dict[str, Any] | None:
        key = f"{exchange_code.strip().lower()}:{market_type.strip().lower()}:{symbol.strip()}"
        now = datetime.now()
        with self._order_book_lock:
            cached = self._order_book_cache.get(key)
            if cached is not None:
                cached_at, payload = cached
                if now - cached_at <= timedelta(seconds=self._order_book_ttl_seconds):
                    return payload

        payload: Dict[str, Any] | None = None
        try:
            payload = exchange_connection_service.fetch_order_book_snapshot(
                exchange_code=exchange_code,
                market_type=market_type,
                symbol=symbol,
                limit=int(strategy_risk_config.order_book_depth_limit or 20),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Order book check degraded to ticker spread: exchange=%s market_type=%s symbol=%s detail=%s",
                exchange_code,
                market_type,
                symbol,
                exc,
            )

        with self._order_book_lock:
            self._order_book_cache[key] = (now, payload)
        return payload

    def _estimate_fill(
        self,
        *,
        levels: List[Any],
        order_amount_usdt: float,
        exchange_code: str = "",
        market_type: str = "",
        symbol: str = "",
    ) -> Dict[str, float]:
        remaining_value = max(0.0, float(order_amount_usdt or 0))
        filled_quantity = 0.0
        filled_value = 0.0
        best_price = 0.0
        contract_size = self._resolve_contract_size(
            exchange_code=exchange_code,
            market_type=market_type,
            symbol=symbol,
        )
        for level in levels:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue
            price = self._parse_float(level[0])
            book_quantity = self._parse_float(level[1])
            base_quantity = book_quantity * contract_size if contract_size > 0 else book_quantity
            if price <= 0 or base_quantity <= 0:
                continue
            if best_price <= 0:
                best_price = price
            level_value = price * base_quantity
            take_value = min(remaining_value, level_value)
            take_quantity = take_value / price if price > 0 else 0.0
            filled_quantity += take_quantity
            filled_value += take_value
            remaining_value -= take_value
            if remaining_value <= 1e-9:
                break

        average_price = filled_value / filled_quantity if filled_quantity > 0 else 0.0
        return {
            "average_price": average_price,
            "best_price": best_price,
            "filled_value_usdt": filled_value,
        }

    def _resolve_contract_size(self, *, exchange_code: str, market_type: str, symbol: str) -> float:
        if str(market_type or "").strip().lower() != "swap":
            return 0.0
        try:
            market_row = market_repository.get_market_by_exchange_symbol(
                exchange_code=str(exchange_code or "").strip().lower(),
                market_type=str(market_type or "").strip().lower(),
                symbol=str(symbol or "").strip(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Resolve contract size failed: exchange=%s market_type=%s symbol=%s detail=%s",
                exchange_code,
                market_type,
                symbol,
                exc,
            )
            return 0.0
        return self._parse_float((market_row or {}).get("contract_size"))

    def _calc_slippage_percent(self, *, side: str, reference_price: float, average_price: float) -> float:
        if reference_price <= 0 or average_price <= 0:
            return 0.0
        if str(side or "").strip().lower() == "buy":
            return max(0.0, (average_price - reference_price) / reference_price * 100)
        return max(0.0, (reference_price - average_price) / reference_price * 100)

    def _parse_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


strategy_execution_quality_service = StrategyExecutionQualityService()


__all__ = [
    "DepthCheckResult",
    "StrategyExecutionQualityService",
    "strategy_execution_quality_service",
]
