"""Execution-centric read-side persistence for arbitrage runtime."""

from __future__ import annotations

from typing import Dict, List

from app.infrastructure.persistence.mysql import mysql_manager


class ArbitrageExecutionRepositoryExecutionQueriesMixin:
    def list_active_open_executions_for_user(self, *, user_id: int, limit: int = 200) -> List[Dict[str, object]]:
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

    def get_execution_by_id(self, execution_id: int) -> Dict[str, object] | None:
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

    def list_open_executions_by_rule_pair(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
    ) -> List[Dict[str, object]]:
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

    def sum_opening_execution_planned_amount_without_position_by_pair(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
    ) -> float:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COALESCE(SUM(ex.planned_order_amount_usdt), 0)
                FROM arbitrage_executions AS ex
                WHERE ex.user_id = %s
                  AND ex.strategy_rule_id = %s
                  AND ex.pair_key = %s
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
                (user_id, strategy_rule_id, pair_key),
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
    ) -> List[Dict[str, object]]:
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
    ) -> Dict[str, object] | None:
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

    def get_latest_active_open_execution_by_pair(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
    ) -> Dict[str, object] | None:
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
                LIMIT 1
                """,
                (user_id, strategy_rule_id, pair_key),
            )
            return cursor.fetchone()

    def get_latest_open_execution_by_user_pair_suffix(
        self,
        *,
        user_id: int,
        pair_suffix: str,
    ) -> Dict[str, object] | None:
        normalized_suffix = str(pair_suffix or "").strip()
        if not normalized_suffix:
            return None
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND action = 'open'
                  AND RIGHT(pair_key, CHAR_LENGTH(%s) + 1) = CONCAT(':', %s)
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, normalized_suffix, normalized_suffix),
            )
            return cursor.fetchone()

    def get_latest_active_open_execution_by_user_pair_suffix(
        self,
        *,
        user_id: int,
        pair_suffix: str,
    ) -> Dict[str, object] | None:
        normalized_suffix = str(pair_suffix or "").strip()
        if not normalized_suffix:
            return None
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND action = 'open'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                  AND RIGHT(pair_key, CHAR_LENGTH(%s) + 1) = CONCAT(':', %s)
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, normalized_suffix, normalized_suffix),
            )
            return cursor.fetchone()

    def get_latest_open_execution_by_rule_pair_status(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
        status: str,
    ) -> Dict[str, object] | None:
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

    def list_active_open_executions(self, *, limit: int = 200) -> List[Dict[str, object]]:
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

    def get_latest_active_close_execution_by_pair(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
    ) -> Dict[str, object] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND pair_key = %s
                  AND action = 'close'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, strategy_rule_id, pair_key),
            )
            return cursor.fetchone()

    def get_latest_close_execution_by_pair(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
    ) -> Dict[str, object] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND pair_key = %s
                  AND action = 'close'
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, strategy_rule_id, pair_key),
            )
            return cursor.fetchone()

    def has_open_close_execution_by_user_pair_suffix(
        self,
        *,
        user_id: int,
        pair_suffix: str,
    ) -> bool:
        normalized_suffix = str(pair_suffix or "").strip()
        if not normalized_suffix:
            return False
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND action = 'close'
                  AND status IN ('pending', 'created', 'processing', 'opening', 'open', 'closing')
                  AND RIGHT(pair_key, CHAR_LENGTH(%s) + 1) = CONCAT(':', %s)
                """,
                (user_id, normalized_suffix, normalized_suffix),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0) > 0

    def list_pair_close_executions(
        self,
        *,
        user_id: int,
        strategy_rule_id: int,
        pair_key: str,
        statuses: List[str] | None = None,
    ) -> List[Dict[str, object]]:
        normalized_statuses = [str(status).strip().lower() for status in (statuses or []) if str(status).strip()]
        params: List[object] = [user_id, strategy_rule_id, pair_key]
        status_clause = ""
        if normalized_statuses:
            placeholders = ", ".join(["%s"] * len(normalized_statuses))
            status_clause = f" AND status IN ({placeholders})"
            params.extend(normalized_statuses)
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT *
                FROM arbitrage_executions
                WHERE user_id = %s
                  AND strategy_rule_id = %s
                  AND pair_key = %s
                  AND action = 'close'
                  {status_clause}
                ORDER BY id DESC
                """,
                tuple(params),
            )
            return list(cursor.fetchall())

    def get_latest_close_execution_by_source(self, *, source_execution_id: int) -> Dict[str, object] | None:
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

    def count_closed_close_executions_by_source(self, *, source_execution_id: int) -> int:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM arbitrage_executions
                WHERE source_execution_id = %s
                  AND action = 'close'
                  AND status = 'closed'
                """,
                (source_execution_id,),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0)

    def count_funding_fee_receipts_by_execution(self, *, execution_id: int) -> int:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM arbitrage_funding_fee_receipts
                WHERE execution_id = %s
                """,
                (execution_id,),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0)
