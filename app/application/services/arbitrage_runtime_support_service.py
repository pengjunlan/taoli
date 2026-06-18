"""Shared helpers for arbitrage execution workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from app.infrastructure.cache import market_runtime_cache
from app.infrastructure.persistence.market_repository import market_repository


@dataclass(frozen=True)
class OrderQuantityPlan:
    base_quantity: float
    order_quantity: float
    order_value_usdt: float
    requested_price: float


class ArbitrageRuntimeSupportService:
    def get_latest_price(self, *, exchange_code: str, market_type: str, symbol: str, side: str) -> float:
        ticker = market_runtime_cache.get_ticker(exchange_code, market_type, symbol)
        if ticker is None:
            return 0.0
        normalized_side = str(side or "").strip().lower()
        if normalized_side == "buy":
            return float(ticker.ask_price or ticker.last_price or 0)
        if normalized_side == "sell":
            return float(ticker.bid_price or ticker.last_price or 0)
        return float(ticker.last_price or 0)

    def build_quantity_plan(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbol: str,
        side: str,
        order_amount_usdt: float,
        base_quantity: float | None = None,
    ) -> OrderQuantityPlan:
        market_row = market_repository.get_market_by_exchange_symbol(
            exchange_code=exchange_code,
            market_type=market_type,
            symbol=symbol,
        )
        requested_price = self.get_latest_price(
            exchange_code=exchange_code,
            market_type=market_type,
            symbol=symbol,
            side=side,
        )
        if requested_price <= 0:
            return OrderQuantityPlan(
                base_quantity=0.0,
                order_quantity=0.0,
                order_value_usdt=0.0,
                requested_price=0.0,
            )

        if base_quantity is None or base_quantity <= 0:
            computed_base_quantity = float(order_amount_usdt or 0) / requested_price if requested_price > 0 else 0.0
        else:
            computed_base_quantity = float(base_quantity)

        contract_size = float((market_row or {}).get("contract_size") or 0)
        amount_precision = (market_row or {}).get("amount_precision")
        min_amount = float((market_row or {}).get("min_amount") or 0)

        if market_type == "swap" and contract_size > 0:
            order_quantity = computed_base_quantity / contract_size
        else:
            order_quantity = computed_base_quantity

        order_quantity = self._round_down(order_quantity, amount_precision)
        if min_amount > 0 and order_quantity < min_amount:
            return OrderQuantityPlan(
                base_quantity=0.0,
                order_quantity=0.0,
                order_value_usdt=0.0,
                requested_price=requested_price,
            )

        actual_base_quantity = order_quantity * contract_size if market_type == "swap" and contract_size > 0 else order_quantity
        order_value_usdt = actual_base_quantity * requested_price
        return OrderQuantityPlan(
            base_quantity=actual_base_quantity,
            order_quantity=order_quantity,
            order_value_usdt=order_value_usdt,
            requested_price=requested_price,
        )

    def to_base_quantity(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbol: str,
        order_quantity: float,
    ) -> float:
        market_row = market_repository.get_market_by_exchange_symbol(
            exchange_code=exchange_code,
            market_type=market_type,
            symbol=symbol,
        )
        contract_size = float((market_row or {}).get("contract_size") or 0)
        if market_type == "swap" and contract_size > 0:
            return float(order_quantity or 0) * contract_size
        return float(order_quantity or 0)

    def _round_down(self, value: float, precision: Any) -> float:
        amount = float(value or 0)
        if amount <= 0:
            return 0.0
        try:
            precision_value = float(precision or 0)
        except (TypeError, ValueError):
            precision_value = 0.0

        if precision_value <= 0:
            return amount

        if precision_value >= 1 and float(int(precision_value)) == precision_value:
            decimals = int(precision_value)
            factor = 10 ** decimals
            return int(amount * factor) / factor

        step = precision_value
        return int(amount / step) * step


arbitrage_runtime_support_service = ArbitrageRuntimeSupportService()
