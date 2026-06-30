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


@dataclass(frozen=True)
class PairOrderQuantityPlan:
    shared_base_quantity: float
    left_plan: OrderQuantityPlan
    right_plan: OrderQuantityPlan


class ArbitrageRuntimeSupportService:
    _BASE_QUANTITY_EPSILON = 1e-12
    _MAX_SHARED_BASE_ITERATIONS = 64

    def get_latest_price(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbol: str,
        side: str,
        prefer_post_only: bool = True,
    ) -> float:
        ticker = market_runtime_cache.get_ticker(exchange_code, market_type, symbol)
        if ticker is None:
            return 0.0
        normalized_side = str(side or "").strip().lower()
        if normalized_side == "buy":
            primary_price = ticker.bid_price if prefer_post_only else ticker.ask_price
            return float(primary_price or ticker.last_price or 0)
        if normalized_side == "sell":
            primary_price = ticker.ask_price if prefer_post_only else ticker.bid_price
            return float(primary_price or ticker.last_price or 0)
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
        market_row: Dict[str, Any] | None = None,
        requested_price: float | None = None,
    ) -> OrderQuantityPlan:
        market_row = market_row or market_repository.get_market_by_exchange_symbol(
            exchange_code=exchange_code,
            market_type=market_type,
            symbol=symbol,
        )
        requested_price = float(requested_price or 0) if requested_price is not None else self.get_latest_price(
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

    def build_pair_quantity_plan(
        self,
        *,
        left_exchange_code: str,
        left_market_type: str,
        left_symbol: str,
        left_side: str,
        right_exchange_code: str,
        right_market_type: str,
        right_symbol: str,
        right_side: str,
        order_amount_usdt: float = 0.0,
        base_quantity: float | None = None,
    ) -> PairOrderQuantityPlan | None:
        left_market_row = market_repository.get_market_by_exchange_symbol(
            exchange_code=left_exchange_code,
            market_type=left_market_type,
            symbol=left_symbol,
        )
        right_market_row = market_repository.get_market_by_exchange_symbol(
            exchange_code=right_exchange_code,
            market_type=right_market_type,
            symbol=right_symbol,
        )
        left_price = self.get_latest_price(
            exchange_code=left_exchange_code,
            market_type=left_market_type,
            symbol=left_symbol,
            side=left_side,
        )
        right_price = self.get_latest_price(
            exchange_code=right_exchange_code,
            market_type=right_market_type,
            symbol=right_symbol,
            side=right_side,
        )
        if left_price <= 0 or right_price <= 0:
            return None

        left_seed_plan = self.build_quantity_plan(
            exchange_code=left_exchange_code,
            market_type=left_market_type,
            symbol=left_symbol,
            side=left_side,
            order_amount_usdt=order_amount_usdt,
            base_quantity=base_quantity,
            market_row=left_market_row,
            requested_price=left_price,
        )
        right_seed_plan = self.build_quantity_plan(
            exchange_code=right_exchange_code,
            market_type=right_market_type,
            symbol=right_symbol,
            side=right_side,
            order_amount_usdt=order_amount_usdt,
            base_quantity=base_quantity,
            market_row=right_market_row,
            requested_price=right_price,
        )
        if left_seed_plan.order_quantity <= 0 or right_seed_plan.order_quantity <= 0:
            return None

        shared_base_quantity = min(left_seed_plan.base_quantity, right_seed_plan.base_quantity)
        if shared_base_quantity <= 0:
            return None

        for _ in range(self._MAX_SHARED_BASE_ITERATIONS):
            left_plan = self.build_quantity_plan(
                exchange_code=left_exchange_code,
                market_type=left_market_type,
                symbol=left_symbol,
                side=left_side,
                order_amount_usdt=0,
                base_quantity=shared_base_quantity,
                market_row=left_market_row,
                requested_price=left_price,
            )
            right_plan = self.build_quantity_plan(
                exchange_code=right_exchange_code,
                market_type=right_market_type,
                symbol=right_symbol,
                side=right_side,
                order_amount_usdt=0,
                base_quantity=shared_base_quantity,
                market_row=right_market_row,
                requested_price=right_price,
            )
            if left_plan.order_quantity <= 0 or right_plan.order_quantity <= 0:
                return None

            left_base_quantity = float(left_plan.base_quantity or 0)
            right_base_quantity = float(right_plan.base_quantity or 0)
            if self._same_base_quantity(left_base_quantity, right_base_quantity):
                final_shared_quantity = min(left_base_quantity, right_base_quantity)
                return PairOrderQuantityPlan(
                    shared_base_quantity=final_shared_quantity,
                    left_plan=left_plan,
                    right_plan=right_plan,
                )

            next_shared_quantity = min(left_base_quantity, right_base_quantity)
            if next_shared_quantity <= 0:
                return None
            if self._same_base_quantity(next_shared_quantity, shared_base_quantity):
                return None
            shared_base_quantity = next_shared_quantity

        return None

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

    def _same_base_quantity(self, left_value: float, right_value: float) -> bool:
        return abs(float(left_value or 0) - float(right_value or 0)) <= self._BASE_QUANTITY_EPSILON


arbitrage_runtime_support_service = ArbitrageRuntimeSupportService()
