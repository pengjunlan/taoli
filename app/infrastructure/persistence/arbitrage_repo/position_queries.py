"""Position-centric read-side persistence for arbitrage runtime."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.infrastructure.persistence.mysql import mysql_manager


class ArbitrageExecutionRepositoryPositionQueriesMixin:
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

    def list_open_positions_for_user(self, *, user_id: int, limit: int = 20) -> List[Dict[str, object]]:
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
    ) -> List[Dict[str, object]]:
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
    ) -> Dict[str, object] | None:
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
