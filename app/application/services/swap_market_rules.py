"""Shared filters for supported U-margined perpetual markets."""

from __future__ import annotations

from typing import Any, Mapping


def is_u_margin_linear_swap_market(row: Mapping[str, Any] | None) -> bool:
    if not row:
        return False

    market_type = str(row.get("market_type") or row.get("type") or "").strip().lower()
    quote_asset = str(row.get("quote_asset") or row.get("quote") or "").strip().upper()
    settle_asset = str(row.get("settle_asset") or row.get("settle") or quote_asset).strip().upper()

    return (
        market_type == "swap"
        and bool(row.get("is_linear") or row.get("linear"))
        and quote_asset == "USDT"
        and settle_asset == "USDT"
    )
