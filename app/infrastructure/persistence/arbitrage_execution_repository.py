"""Persistence for local arbitrage execution, order, fill and position data."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.infrastructure.persistence.mysql import mysql_manager


class MySQLArbitrageExecutionRepository:
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

    def get_position_quantity(
        self,
        *,
        exchange_account_id: int,
        market_type: str,
        symbol: str,
        position_side: str | None = None,
    ) -> Optional[float]:
        if exchange_account_id <= 0 or not market_type or not symbol:
            return None

        params: List[Any] = [exchange_account_id, market_type, symbol]
        side_filter = ""
        if position_side:
            side_filter = " AND position_side IN (%s, 'net')"
            params.append(position_side)

        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT quantity, position_side
                FROM arbitrage_positions
                WHERE exchange_account_id = %s
                  AND market_type = %s
                  AND symbol = %s
                  AND status = 'open'
                  {side_filter}
                ORDER BY
                    CASE
                        WHEN position_side = %s THEN 0
                        WHEN position_side = 'net' THEN 1
                        ELSE 2
                    END,
                    updated_at DESC
                LIMIT 1
                """,
                tuple(params + [position_side or "net"]),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            try:
                return float(row.get("quantity") or 0)
            except (TypeError, ValueError):
                return 0.0

    def list_recent_order_legs_for_user(self, *, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit or 20))
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    ol.id,
                    ol.execution_id,
                    ol.leg_role,
                    ol.exchange_code,
                    ol.market_type,
                    ol.symbol,
                    ol.side,
                    ol.position_side,
                    ol.status,
                    ol.status_message,
                    ol.requested_price,
                    ol.requested_quantity,
                    ol.requested_value_usdt,
                    ol.retry_count,
                    ol.average_fill_price,
                    ol.filled_quantity,
                    ol.filled_value_usdt,
                    ol.submitted_at,
                    ol.acknowledged_at,
                    ol.closed_at,
                    ol.created_at,
                    ex.strategy_rule_name,
                    ex.strategy_type,
                    ex.trigger_reason,
                    ex.pair_key,
                    ex.action,
                    ex.status AS execution_status,
                    ex.updated_at AS execution_updated_at
                FROM arbitrage_order_legs AS ol
                INNER JOIN arbitrage_executions AS ex
                    ON ex.id = ol.execution_id
                WHERE ol.user_id = %s
                ORDER BY COALESCE(ol.submitted_at, ol.acknowledged_at, ol.created_at) DESC, ol.id DESC
                LIMIT %s
                """,
                (user_id, safe_limit),
            )
            return list(cursor.fetchall())

    def list_active_open_executions_for_user(self, *, user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit or 200))
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND action = 'open'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                ORDER BY updated_at DESC, id DESC
                LIMIT %s
                """,
                (user_id, safe_limit),
            )
            return list(cursor.fetchall())

    def get_execution_by_id(self, execution_id: int) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE id = %s
                LIMIT 1
                """,
                (execution_id,),
            )
            return cursor.fetchone()

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

    def list_open_executions_by_rule_pair(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
    ) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND pair_key = %s
                  AND action = 'open'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                ORDER BY id DESC
                """,
                (user_id, strategy_rule_id, pair_key),
            )
            return list(cursor.fetchall())

    def has_active_open_execution_by_rule_pair(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
    ) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND pair_key = %s
                  AND action = 'open'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'closing')
                """,
                (user_id, strategy_rule_id, pair_key),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0) > 0

    def count_open_executions_by_rule(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
    ) -> int:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND action = 'open'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                """,
                (user_id, strategy_rule_id),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0)

    def list_active_open_pair_keys_by_rule(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
    ) -> List[str]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT DISTINCT pair_key
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND action = 'open'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                  AND pair_key <> ''
                ORDER BY pair_key ASC
                """,
                (user_id, strategy_rule_id),
            )
            return [
                str(row.get("pair_key") or "").strip()
                for row in cursor.fetchall()
                if str(row.get("pair_key") or "").strip()
            ]

    def sum_open_execution_planned_amount_by_rule(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
    ) -> float:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COALESCE(SUM(planned_order_amount_usdt), 0)
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND action = 'open'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                """,
                (user_id, strategy_rule_id),
            )
            row = cursor.fetchone()
            return float(row[0] if row and row[0] is not None else 0.0)

    def sum_live_position_equivalent_amount_by_rule(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
    ) -> float:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COALESCE(SUM(execution_exposure), 0)
                FROM (
                    SELECT
                        CASE
                            WHEN ex.action = 'close' AND ex.source_execution_id IS NOT NULL
                                THEN ex.source_execution_id
                            ELSE p.opened_by_execution_id
                        END AS runtime_execution_id,
                        MAX(
                            CASE
                                WHEN p.market_value_usdt > 0 THEN p.market_value_usdt
                                WHEN p.mark_price > 0 AND p.quantity > 0 THEN p.mark_price * p.quantity
                                WHEN p.avg_entry_price > 0 AND p.quantity > 0 THEN p.avg_entry_price * p.quantity
                                ELSE 0
                            END
                        ) AS execution_exposure
                    FROM arbitrage_positions AS p
                    LEFT JOIN arbitrage_executions AS ex
                        ON ex.id = p.opened_by_execution_id
                    LEFT JOIN arbitrage_executions AS source_ex
                        ON ex.action = 'close'
                       AND source_ex.id = ex.source_execution_id
                    WHERE p.user_id = %s
                      AND p.status = 'open'
                      AND p.quantity > 0
                      AND COALESCE(source_ex.strategy_rule_id, ex.strategy_rule_id) = %s
                    GROUP BY runtime_execution_id
                ) AS runtime_exposures
                """,
                (user_id, strategy_rule_id),
            )
            row = cursor.fetchone()
            return float(row[0] if row and row[0] is not None else 0.0)

    def sum_live_position_quantity_by_rule(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
    ) -> float:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COALESCE(SUM(runtime_quantity), 0)
                FROM (
                    SELECT
                        CASE
                            WHEN ex.action = 'close' AND ex.source_execution_id IS NOT NULL
                                THEN ex.source_execution_id
                            ELSE p.opened_by_execution_id
                        END AS runtime_execution_id,
                        MAX(ABS(p.quantity)) AS runtime_quantity
                    FROM arbitrage_positions AS p
                    LEFT JOIN arbitrage_executions AS ex
                        ON ex.id = p.opened_by_execution_id
                    LEFT JOIN arbitrage_executions AS source_ex
                        ON ex.action = 'close'
                       AND source_ex.id = ex.source_execution_id
                    WHERE p.user_id = %s
                      AND p.status = 'open'
                      AND p.quantity > 0
                      AND COALESCE(source_ex.strategy_rule_id, ex.strategy_rule_id) = %s
                    GROUP BY runtime_execution_id
                ) AS runtime_quantities
                """,
                (user_id, strategy_rule_id),
            )
            row = cursor.fetchone()
            return float(row[0] if row and row[0] is not None else 0.0)

    def sum_opening_execution_planned_amount_without_position_by_rule(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
    ) -> float:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COALESCE(SUM(ex.planned_order_amount_usdt), 0)
                FROM arbitrage_executions AS ex
                WHERE ex.user_id = %s
                  AND ex.strategy_rule_id = %s
                  AND ex.action = 'open'
                  AND ex.status IN ('pending', 'created', 'processing', 'opening')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM arbitrage_positions AS p
                      LEFT JOIN arbitrage_executions AS px
                          ON px.id = p.opened_by_execution_id
                      WHERE p.user_id = ex.user_id
                        AND p.status = 'open'
                        AND p.quantity > 0
                        AND (
                            p.opened_by_execution_id = ex.id
                            OR (
                                px.action = 'close'
                                AND px.source_execution_id = ex.id
                            )
                        )
                  )
                """,
                (user_id, strategy_rule_id),
            )
            row = cursor.fetchone()
            return float(row[0] if row and row[0] is not None else 0.0)

    def sum_committed_position_amount_by_rule(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
    ) -> float:
        live_amount = self.sum_live_position_equivalent_amount_by_rule(
            user_id=user_id,
            strategy_rule_id=strategy_rule_id,
        )
        opening_amount = self.sum_opening_execution_planned_amount_without_position_by_rule(
            user_id=user_id,
            strategy_rule_id=strategy_rule_id,
        )
        return float(live_amount + opening_amount)

    def list_executions_for_rule_action(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        action: str,
    ) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND action = %s
                ORDER BY id DESC
                """,
                (user_id, strategy_rule_id, action),
            )
            return list(cursor.fetchall())

    def get_latest_open_execution_by_pair(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
    ) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND pair_key = %s
                  AND action = 'open'
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, strategy_rule_id, pair_key),
            )
            return cursor.fetchone()

    def get_latest_open_execution_by_rule_pair_status(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
        status: str,
    ) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND pair_key = %s
                  AND action = 'open'
                  AND status = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, strategy_rule_id, pair_key, status),
            )
            return cursor.fetchone()

    def list_active_open_executions(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit or 200))
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE action = 'open'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                ORDER BY id ASC
                LIMIT %s
                """,
                (safe_limit,),
            )
            return list(cursor.fetchall())

    def has_open_close_execution(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
    ) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND pair_key = %s
                  AND action = 'close'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                """,
                (user_id, strategy_rule_id, pair_key),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0) > 0

    def get_latest_close_execution_by_source(self, *, source_execution_id: int) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE source_execution_id = %s
                  AND action = 'close'
                ORDER BY id DESC
                LIMIT 1
                """,
                (source_execution_id,),
            )
            return cursor.fetchone()

    def list_pending_order_legs(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit or 20))
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    ol.*,
                    ex.strategy_type,
                    ex.strategy_rule_id,
                    ex.strategy_rule_name,
                    ex.symbol AS execution_symbol,
                    ex.base_asset,
                    ex.quote_asset,
                    ex.pair_key,
                    ex.action,
                    ex.status AS execution_status
                FROM arbitrage_order_legs AS ol
                INNER JOIN arbitrage_executions AS ex
                    ON ex.id = ol.execution_id
                WHERE ol.status IN ('pending', 'created', 'submitting', 'submitted', 'partial')
                ORDER BY ol.id ASC
                LIMIT %s
                """,
                (safe_limit,),
            )
            return list(cursor.fetchall())

    def list_order_legs_by_execution(self, *, execution_id: int) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_order_legs
                WHERE execution_id = %s
                ORDER BY id ASC
                """,
                (execution_id,),
            )
            return list(cursor.fetchall())

    def list_recent_fill_records_for_user(self, *, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit or 20))
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    fr.id,
                    fr.order_leg_id,
                    fr.exchange_code,
                    fr.market_type,
                    fr.symbol,
                    fr.side,
                    fr.fill_price,
                    fr.fill_quantity,
                    fr.fill_value_usdt,
                    fr.fee_amount,
                    fr.fee_asset,
                    fr.filled_at,
                    fr.created_at
                FROM arbitrage_fill_records AS fr
                WHERE fr.user_id = %s
                ORDER BY COALESCE(fr.filled_at, fr.created_at) DESC, fr.id DESC
                LIMIT %s
                """,
                (user_id, safe_limit),
            )
            return list(cursor.fetchall())

    def list_open_positions_for_user(self, *, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit or 20))
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    p.id,
                    CASE
                        WHEN ex.action = 'close' AND ex.source_execution_id IS NOT NULL
                            THEN ex.source_execution_id
                        ELSE p.opened_by_execution_id
                    END AS runtime_execution_id,
                    p.opened_by_execution_id,
                    p.exchange_code,
                    p.market_type,
                    p.symbol,
                    p.position_side,
                    p.quantity,
                    p.avg_entry_price,
                    p.mark_price,
                    p.market_value_usdt,
                    p.realized_pnl_usdt,
                    p.unrealized_pnl_usdt,
                    p.status,
                    p.updated_at,
                    COALESCE(source_ex.strategy_rule_name, ex.strategy_rule_name) AS strategy_rule_name
                FROM arbitrage_positions AS p
                LEFT JOIN arbitrage_executions AS ex
                    ON ex.id = p.opened_by_execution_id
                LEFT JOIN arbitrage_executions AS source_ex
                    ON ex.action = 'close'
                   AND source_ex.id = ex.source_execution_id
                WHERE p.user_id = %s
                  AND p.status = 'open'
                  AND p.quantity > 0
                ORDER BY p.updated_at DESC, p.id DESC
                LIMIT %s
                """,
                (user_id, safe_limit),
            )
            return list(cursor.fetchall())

    def list_open_positions_for_accounts(
        self,
        *,
        user_id: int,
        account_ids: List[int],
        symbols: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        normalized_account_ids = sorted({int(account_id) for account_id in account_ids if int(account_id) > 0})
        if not normalized_account_ids:
            return []
        normalized_symbols = sorted({str(symbol).strip() for symbol in (symbols or []) if str(symbol).strip()})
        account_placeholders = ", ".join(["%s"] * len(normalized_account_ids))
        params: List[Any] = [user_id, *normalized_account_ids]
        symbol_clause = ""
        if normalized_symbols:
            symbol_clause = f" AND symbol IN ({', '.join(['%s'] * len(normalized_symbols))})"
            params.extend(normalized_symbols)
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT
                    id,
                    user_id,
                    exchange_account_id,
                    exchange_code,
                    market_type,
                    symbol,
                    position_side,
                    quantity,
                    avg_entry_price,
                    mark_price,
                    market_value_usdt,
                    realized_pnl_usdt,
                    unrealized_pnl_usdt,
                    status,
                    last_synced_at,
                    created_at,
                    updated_at
                FROM arbitrage_positions
                WHERE user_id = %s
                  AND exchange_account_id IN ({account_placeholders})
                  AND status = 'open'
                  AND quantity > 0
                  {symbol_clause}
                ORDER BY updated_at DESC, id DESC
                """,
                tuple(params),
            )
            return list(cursor.fetchall())

    def get_open_position(
        self,
        *,
        exchange_account_id: int,
        market_type: str,
        symbol: str,
        position_side: str,
    ) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_positions
                WHERE exchange_account_id = %s
                  AND market_type = %s
                  AND symbol = %s
                  AND position_side = %s
                  AND status = 'open'
                LIMIT 1
                """,
                (exchange_account_id, market_type, symbol, position_side),
            )
            return cursor.fetchone()


arbitrage_execution_repository = MySQLArbitrageExecutionRepository()
