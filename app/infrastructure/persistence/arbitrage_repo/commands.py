"""Write-side persistence for arbitrage executions."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, List

from app.infrastructure.persistence.mysql import mysql_manager


class ArbitrageExecutionRepositoryCommandsMixin:
    def create_execution(
        self,
        *,
        user_id: int,
        strategy_type: str,
        source_execution_id: int | None = None,
        pair_key: str,
        action: str,
        symbol: str,
        base_asset: str,
        quote_asset: str,
        left_exchange_code: str,
        right_exchange_code: str,
        left_market_type: str,
        right_market_type: str,
        left_symbol: str,
        right_symbol: str,
        planned_order_amount_usdt: float,
        max_position_usdt: float,
        trigger_metric_primary: str = "",
        trigger_metric_secondary: str = "",
        trigger_metric_risk: str = "",
        trigger_reason: str = "",
        strategy_rule_id: int | None = None,
        strategy_rule_name: str = "",
        status: str = "pending",
    ) -> int:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO arbitrage_executions (
                    user_id,
                    strategy_type,
                    strategy_rule_id,
                    strategy_rule_name,
                    source_execution_id,
                    pair_key,
                    action,
                    symbol,
                    base_asset,
                    quote_asset,
                    left_exchange_code,
                    right_exchange_code,
                    left_market_type,
                    right_market_type,
                    left_symbol,
                    right_symbol,
                    planned_order_amount_usdt,
                    max_position_usdt,
                    trigger_metric_primary,
                    trigger_metric_secondary,
                    trigger_metric_risk,
                    trigger_reason,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    strategy_type,
                    strategy_rule_id,
                    strategy_rule_name,
                    source_execution_id,
                    pair_key,
                    action,
                    symbol,
                    base_asset,
                    quote_asset,
                    left_exchange_code,
                    right_exchange_code,
                    left_market_type,
                    right_market_type,
                    left_symbol,
                    right_symbol,
                    planned_order_amount_usdt,
                    max_position_usdt,
                    trigger_metric_primary,
                    trigger_metric_secondary,
                    trigger_metric_risk,
                    trigger_reason,
                    status,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def create_order_leg(
        self,
        *,
        execution_id: int,
        user_id: int,
        exchange_account_id: int | None,
        leg_role: str,
        position_side: str,
        exchange_code: str,
        market_type: str,
        symbol: str,
        side: str,
        order_type: str,
        requested_price: float,
        requested_quantity: float,
        requested_value_usdt: float,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
        status: str = "pending",
        status_message: str = "",
        submitted_at: datetime | None = None,
        acknowledged_at: datetime | None = None,
    ) -> int:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO arbitrage_order_legs (
                    execution_id,
                    user_id,
                    exchange_account_id,
                    leg_role,
                    position_side,
                    exchange_code,
                    market_type,
                    symbol,
                    side,
                    order_type,
                    client_order_id,
                    exchange_order_id,
                    requested_price,
                    requested_quantity,
                    requested_value_usdt,
                    status,
                    status_message,
                    submitted_at,
                    acknowledged_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    execution_id,
                    user_id,
                    exchange_account_id,
                    leg_role,
                    position_side,
                    exchange_code,
                    market_type,
                    symbol,
                    side,
                    order_type,
                    client_order_id,
                    exchange_order_id,
                    requested_price,
                    requested_quantity,
                    requested_value_usdt,
                    status,
                    status_message,
                    submitted_at,
                    acknowledged_at,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def update_order_leg_status(
        self,
        *,
        order_leg_id: int,
        status: str,
        status_message: str = "",
        exchange_order_id: str | None = None,
        client_order_id: str | None = None,
        requested_price: float | None = None,
        requested_quantity: float | None = None,
        requested_value_usdt: float | None = None,
        average_fill_price: float | None = None,
        filled_quantity: float | None = None,
        filled_value_usdt: float | None = None,
        submitted_at: datetime | None = None,
        acknowledged_at: datetime | None = None,
        closed_at: datetime | None = None,
        retry_count: int | None = None,
        last_retry_at: datetime | None = None,
    ) -> None:
        assignments = ["status = %s", "status_message = %s"]
        params: List[Any] = [status, status_message, order_leg_id]

        optional_fields = [
            ("exchange_order_id", exchange_order_id),
            ("client_order_id", client_order_id),
            ("requested_price", requested_price),
            ("requested_quantity", requested_quantity),
            ("requested_value_usdt", requested_value_usdt),
            ("average_fill_price", average_fill_price),
            ("filled_quantity", filled_quantity),
            ("filled_value_usdt", filled_value_usdt),
            ("submitted_at", submitted_at),
            ("acknowledged_at", acknowledged_at),
            ("retry_count", retry_count),
            ("last_retry_at", last_retry_at),
            ("closed_at", closed_at),
        ]
        for column, value in optional_fields:
            if value is None:
                continue
            assignments.append(f"{column} = %s")
            params.insert(-1, value)

        query = f"""
            UPDATE arbitrage_order_legs
            SET {", ".join(assignments)}
            WHERE id = %s
        """
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(query, tuple(params))
            connection.commit()

    def create_fill_record(
        self,
        *,
        execution_id: int,
        order_leg_id: int,
        user_id: int,
        exchange_account_id: int | None,
        exchange_code: str,
        market_type: str,
        symbol: str,
        position_side: str,
        side: str,
        fill_price: float,
        fill_quantity: float,
        fill_value_usdt: float,
        fee_amount: float = 0.0,
        fee_asset: str = "",
        liquidity: str = "",
        exchange_fill_id: str | None = None,
        filled_at: datetime | None = None,
    ) -> int:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO arbitrage_fill_records (
                    execution_id,
                    order_leg_id,
                    user_id,
                    exchange_account_id,
                    exchange_code,
                    market_type,
                    symbol,
                    position_side,
                    side,
                    exchange_fill_id,
                    fill_price,
                    fill_quantity,
                    fill_value_usdt,
                    fee_amount,
                    fee_asset,
                    liquidity,
                    filled_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    execution_id,
                    order_leg_id,
                    user_id,
                    exchange_account_id,
                    exchange_code,
                    market_type,
                    symbol,
                    position_side,
                    side,
                    exchange_fill_id,
                    fill_price,
                    fill_quantity,
                    fill_value_usdt,
                    fee_amount,
                    fee_asset,
                    liquidity,
                    filled_at,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def upsert_position(
        self,
        *,
        user_id: int,
        exchange_account_id: int | None,
        exchange_code: str,
        market_type: str,
        symbol: str,
        base_asset: str,
        quote_asset: str,
        position_side: str,
        quantity: float,
        avg_entry_price: float = 0.0,
        mark_price: float = 0.0,
        market_value_usdt: float = 0.0,
        realized_pnl_usdt: float = 0.0,
        unrealized_pnl_usdt: float = 0.0,
        opened_by_execution_id: int | None = None,
        last_order_leg_id: int | None = None,
        last_fill_id: int | None = None,
        status: str = "open",
        last_synced_at: datetime | None = None,
    ) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO arbitrage_positions (
                    user_id,
                    exchange_account_id,
                    exchange_code,
                    market_type,
                    symbol,
                    base_asset,
                    quote_asset,
                    position_side,
                    quantity,
                    avg_entry_price,
                    mark_price,
                    market_value_usdt,
                    realized_pnl_usdt,
                    unrealized_pnl_usdt,
                    opened_by_execution_id,
                    last_order_leg_id,
                    last_fill_id,
                    status,
                    last_synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    exchange_code = VALUES(exchange_code),
                    user_id = VALUES(user_id),
                    base_asset = VALUES(base_asset),
                    quote_asset = VALUES(quote_asset),
                    quantity = VALUES(quantity),
                    avg_entry_price = VALUES(avg_entry_price),
                    mark_price = VALUES(mark_price),
                    market_value_usdt = VALUES(market_value_usdt),
                    realized_pnl_usdt = VALUES(realized_pnl_usdt),
                    unrealized_pnl_usdt = VALUES(unrealized_pnl_usdt),
                    opened_by_execution_id = VALUES(opened_by_execution_id),
                    last_order_leg_id = VALUES(last_order_leg_id),
                    last_fill_id = VALUES(last_fill_id),
                    status = VALUES(status),
                    last_synced_at = VALUES(last_synced_at),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    exchange_account_id,
                    exchange_code,
                    market_type,
                    symbol,
                    base_asset,
                    quote_asset,
                    position_side,
                    quantity,
                    avg_entry_price,
                    mark_price,
                    market_value_usdt,
                    realized_pnl_usdt,
                    unrealized_pnl_usdt,
                    opened_by_execution_id,
                    last_order_leg_id,
                    last_fill_id,
                    status,
                    last_synced_at or datetime.now(),
                ),
            )
            connection.commit()

    def update_execution_status(self, *, execution_id: int, status: str) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE arbitrage_executions
                SET
                    status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (status, execution_id),
            )
            connection.commit()

    def upsert_funding_fee_receipt(
        self,
        *,
        execution_id: int,
        order_leg_id: int | None,
        user_id: int,
        exchange_account_id: int | None,
        exchange_code: str,
        market_type: str,
        symbol: str,
        position_side: str,
        asset_code: str,
        fee_amount: float,
        exchange_record_id: str,
        settled_at: datetime | None,
        raw_payload: Any,
    ) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO arbitrage_funding_fee_receipts (
                    execution_id,
                    order_leg_id,
                    user_id,
                    exchange_account_id,
                    exchange_code,
                    market_type,
                    symbol,
                    position_side,
                    asset_code,
                    fee_amount,
                    exchange_record_id,
                    settled_at,
                    raw_payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    fee_amount = VALUES(fee_amount),
                    settled_at = VALUES(settled_at),
                    raw_payload = VALUES(raw_payload)
                """,
                (
                    execution_id,
                    order_leg_id,
                    user_id,
                    exchange_account_id,
                    exchange_code,
                    market_type,
                    symbol,
                    position_side,
                    asset_code,
                    fee_amount,
                    exchange_record_id,
                    settled_at,
                    json.dumps(raw_payload, ensure_ascii=True, default=str) if raw_payload is not None else None,
                ),
            )
            connection.commit()
