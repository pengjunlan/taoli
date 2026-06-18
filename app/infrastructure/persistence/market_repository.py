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

    def list_markets_by_exchange(
        self,
        *,
        exchange_code: str,
        market_type: str,
    ) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
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
                WHERE exchange_code = %s
                  AND market_type = %s
                ORDER BY symbol ASC
                """,
                (exchange_code, market_type),
            )
            return list(cursor.fetchall())

    def sync_markets_incremental(
        self,
        *,
        exchange_code: str,
        market_type: str,
        rows: Iterable[Dict[str, Any]],
    ) -> Dict[str, int]:
        items = list(rows)
        incoming_by_symbol = {
            str(item.get("symbol") or "").strip(): item
            for item in items
            if str(item.get("symbol") or "").strip()
        }

        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    symbol,
                    is_active
                FROM exchange_markets
                WHERE exchange_code = %s
                  AND market_type = %s
                """,
                (exchange_code, market_type),
            )
            existing_rows = list(cursor.fetchall())
            existing_by_symbol = {
                str(row.get("symbol") or "").strip(): row
                for row in existing_rows
                if str(row.get("symbol") or "").strip()
            }

            added_count = 0
            reactivated_count = 0
            marked_inactive_count = 0

            insert_payloads = []
            update_payloads = []
            deactivate_ids = []

            for symbol, item in incoming_by_symbol.items():
                existing = existing_by_symbol.get(symbol)
                if existing is None:
                    insert_payloads.append(
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
                    )
                    added_count += 1
                    continue

                if not bool(existing.get("is_active")):
                    update_payloads.append(
                        (
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
                            int(existing["id"]),
                        )
                    )
                    reactivated_count += 1

            for symbol, existing in existing_by_symbol.items():
                if symbol in incoming_by_symbol:
                    continue
                if bool(existing.get("is_active")):
                    deactivate_ids.append(int(existing["id"]))
                    marked_inactive_count += 1

            if insert_payloads:
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
                    insert_payloads,
                )

            if update_payloads:
                cursor.executemany(
                    """
                    UPDATE exchange_markets
                    SET symbol_normalized = %s,
                        base_asset = %s,
                        quote_asset = %s,
                        settle_asset = %s,
                        is_contract = %s,
                        is_linear = %s,
                        contract_size = %s,
                        price_precision = %s,
                        amount_precision = %s,
                        min_amount = %s,
                        supports_funding = %s,
                        supports_ws = %s,
                        is_active = %s,
                        synced_at = %s
                    WHERE id = %s
                    """,
                    update_payloads,
                )

            if deactivate_ids:
                cursor.executemany(
                    """
                    UPDATE exchange_markets
                    SET is_active = 0
                    WHERE id = %s
                    """,
                    [(item_id,) for item_id in deactivate_ids],
                )

            connection.commit()

        return {
            "added_count": added_count,
            "reactivated_count": reactivated_count,
            "marked_inactive_count": marked_inactive_count,
            "incoming_count": len(incoming_by_symbol),
            "existing_count": len(existing_by_symbol),
        }

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

        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(query, tuple(params))
            return list(cursor.fetchall())

    def count_active_pairs(self, *, pair_type: str | None = None) -> int:
        query = """
            SELECT COUNT(*) AS total
            FROM exchange_market_pairs
            WHERE is_active = 1
        """
        params: List[Any] = []
        if pair_type:
            query += " AND pair_type = %s"
            params.append(pair_type)

        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(query, tuple(params))
            row = cursor.fetchone() or {}
            return int(row.get("total") or 0)

    def get_market_by_exchange_symbol(
        self,
        *,
        exchange_code: str,
        market_type: str,
        symbol: str,
    ) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
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
                WHERE exchange_code = %s
                  AND market_type = %s
                  AND symbol = %s
                LIMIT %s
                """,
                (exchange_code, market_type, symbol, 1),
            )
            return cursor.fetchone()


market_repository = MySQLMarketRepository()
