"""Order and fill read-side persistence for arbitrage runtime."""

from __future__ import annotations

from typing import Dict, List

from app.infrastructure.persistence.mysql import mysql_manager


class ArbitrageExecutionRepositoryOrderQueriesMixin:
    def list_recent_order_legs_for_user(self, *, user_id: int, limit: int = 20) -> List[Dict[str, object]]:
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

    def list_pending_order_legs(self, *, limit: int = 20) -> List[Dict[str, object]]:
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

    def list_order_legs_by_execution(self, *, execution_id: int) -> List[Dict[str, object]]:
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

    def list_recent_fill_records_for_user(self, *, user_id: int, limit: int = 20) -> List[Dict[str, object]]:
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
