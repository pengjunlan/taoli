"""MySQL-backed repository for exchange markets and generated arbitrage pairs."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.infrastructure.persistence import mysql_manager


class MySQLMarketRepository:
    def replace_markets(
        self,
        *,
        exchange_code: str,
        market_type: str,
        rows: Iterable[Dict[str, Any]],
    ) -> None:
        items = list(rows)
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                DELETE FROM exchange_markets
                WHERE exchange_code = %s AND market_type = %s
                """,
                (exchange_code, market_type),
            )

            if items:
                cursor.executemany(
                    """
                    INSERT INTO exchange_markets (
                        exchange_code,
                        market_type,
                        symbol,
                        symbol_normalized,
                        base_asset,
                        quote_asset,
                        settle_asset,
                        is_contract,
                        is_linear,
                        contract_size,
                        price_precision,
                        amount_precision,
                        min_amount,
                        supports_funding,
                        supports_ws,
                        is_active,
                        synced_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            exchange_code,
                            market_type,
                            str(item["symbol"]),
                            str(item["symbol_normalized"]),
                            str(item["base_asset"]),
                            str(item["quote_asset"]),
                            str(item["settle_asset"]),
                            1 if item.get("is_contract") else 0,
                            1 if item.get("is_linear") else 0,
                            float(item.get("contract_size") or 0),
                            float(item.get("price_precision") or 0),
                            float(item.get("amount_precision") or 0),
                            float(item.get("min_amount") or 0),
                            1 if item.get("supports_funding") else 0,
                            1 if item.get("supports_ws", True) else 0,
                            1,
                            item["synced_at"],
                        )
                        for item in items
                    ],
                )
            connection.commit()

    def list_active_markets(
        self,
        *,
        exchange_codes: List[str] | None = None,
        market_type: str | None = None,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                id,
                exchange_code,
                market_type,
                symbol,
                symbol_normalized,
                base_asset,
                quote_asset,
                settle_asset,
                is_contract,
                is_linear,
                contract_size,
                price_precision,
                amount_precision,
                min_amount,
                supports_funding,
                supports_ws,
                is_active,
                synced_at
            FROM exchange_markets
            WHERE is_active = 1
        """
        params: List[Any] = []
        if exchange_codes:
            query += f" AND exchange_code IN ({', '.join(['%s'] * len(exchange_codes))})"
            params.extend(exchange_codes)
        if market_type:
            query += " AND market_type = %s"
            params.append(market_type)
        query += " ORDER BY exchange_code ASC, symbol_normalized ASC"

        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(query, tuple(params))
            return list(cursor.fetchall())

    def replace_pairs(self, *, pair_type: str, rows: Iterable[Dict[str, Any]]) -> None:
        items = list(rows)
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                DELETE FROM exchange_market_pairs
                WHERE pair_type = %s
                """,
                (pair_type,),
            )
            if items:
                cursor.executemany(
                    """
                    INSERT INTO exchange_market_pairs (
                        pair_type,
                        pair_key,
                        left_exchange_code,
                        right_exchange_code,
                        left_market_type,
                        right_market_type,
                        symbol_normalized,
                        left_symbol,
                        right_symbol,
                        base_asset,
                        quote_asset,
                        settle_asset,
                        match_mode,
                        pair_reason,
                        is_active,
                        generated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            pair_type,
                            str(item["pair_key"]),
                            str(item["left_exchange_code"]),
                            str(item["right_exchange_code"]),
                            str(item["left_market_type"]),
                            str(item["right_market_type"]),
                            str(item["symbol_normalized"]),
                            str(item["left_symbol"]),
                            str(item["right_symbol"]),
                            str(item["base_asset"]),
                            str(item["quote_asset"]),
                            str(item["settle_asset"]),
                            str(item.get("match_mode") or "auto"),
                            str(item.get("pair_reason") or ""),
                            1,
                            item["generated_at"],
                        )
                        for item in items
                    ],
                )
            connection.commit()

    def list_active_pairs(self, *, pair_type: str | None = None) -> List[Dict[str, Any]]:
        query = """
            SELECT
                id,
                pair_type,
                pair_key,
                left_exchange_code,
                right_exchange_code,
                left_market_type,
                right_market_type,
                symbol_normalized,
                left_symbol,
                right_symbol,
                base_asset,
                quote_asset,
                settle_asset,
                match_mode,
                pair_reason,
                is_active,
                generated_at
            FROM exchange_market_pairs
            WHERE is_active = 1
        """
        params: List[Any] = []
        if pair_type:
            query += " AND pair_type = %s"
            params.append(pair_type)
        query += " ORDER BY symbol_normalized ASC, left_exchange_code ASC, right_exchange_code ASC"

        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(query, tuple(params))
            return list(cursor.fetchall())


market_repository = MySQLMarketRepository()
