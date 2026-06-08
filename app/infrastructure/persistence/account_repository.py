"""MySQL-backed account repository."""

from __future__ import annotations

from typing import Any, Dict, List

from app.domain.entities import AccountAddress, ExchangeAccount
from app.infrastructure.persistence import mysql_manager


class MySQLAccountRepository:
    """Handles exchange account and funding address persistence."""

    def get_account_with_address_by_id(self, account_id: int, user_id: int) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    a.id,
                    a.user_id,
                    a.market_type,
                    a.exchange_code,
                    a.account_name,
                    a.api_key,
                    a.api_secret,
                    a.api_passphrase,
                    a.is_active,
                    a.created_at,
                    a.updated_at,
                    fa.network,
                    fa.address_value,
                    fa.memo_tag,
                    fa.created_at AS address_created_at,
                    fa.updated_at AS address_updated_at
                FROM exchange_accounts AS a
                LEFT JOIN account_funding_addresses AS fa
                    ON fa.account_id = a.id
                WHERE a.id = %s AND a.user_id = %s
                LIMIT 1
                """,
                (account_id, user_id),
            )
            return cursor.fetchone()

    def create_account(
        self,
        *,
        user_id: int,
        market_type: str,
        exchange_code: str,
        account_name: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
    ) -> ExchangeAccount:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                INSERT INTO exchange_accounts (
                    user_id,
                    market_type,
                    exchange_code,
                    account_name,
                    api_key,
                    api_secret,
                    api_passphrase
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, market_type, exchange_code, account_name, api_key, api_secret, api_passphrase),
            )
            connection.commit()

            cursor.execute(
                """
                SELECT
                    id,
                    user_id,
                    market_type,
                    exchange_code,
                    account_name,
                    api_key,
                    api_secret,
                    api_passphrase,
                    is_active,
                    created_at,
                    updated_at
                FROM exchange_accounts
                WHERE id = %s
                """,
                (cursor.lastrowid,),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._build_account(row)

    def update_account(
        self,
        *,
        account_id: int,
        user_id: int,
        market_type: str,
        exchange_code: str,
        account_name: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
    ) -> ExchangeAccount | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                UPDATE exchange_accounts
                SET
                    market_type = %s,
                    exchange_code = %s,
                    account_name = %s,
                    api_key = %s,
                    api_secret = %s,
                    api_passphrase = %s
                WHERE id = %s AND user_id = %s
                """,
                (
                    market_type,
                    exchange_code,
                    account_name,
                    api_key,
                    api_secret,
                    api_passphrase,
                    account_id,
                    user_id,
                ),
            )
            connection.commit()

            # MySQL returns rowcount = 0 when the submitted values are identical
            # to the current row, so we must re-query ownership instead of
            # treating that case as "account not found".
            cursor.execute(
                """
                SELECT
                    id,
                    user_id,
                    market_type,
                    exchange_code,
                    account_name,
                    api_key,
                    api_secret,
                    api_passphrase,
                    is_active,
                    created_at,
                    updated_at
                FROM exchange_accounts
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (account_id, user_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._build_account(row)

    def create_address(
        self,
        *,
        account_id: int,
        network: str,
        address_value: str,
        memo_tag: str,
    ) -> AccountAddress:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                INSERT INTO account_funding_addresses (
                    account_id,
                    network,
                    address_value,
                    memo_tag
                )
                VALUES (%s, %s, %s, %s)
                """,
                (account_id, network, address_value, memo_tag),
            )
            connection.commit()

            cursor.execute(
                """
                SELECT
                    id,
                    account_id,
                    network,
                    address_value,
                    memo_tag,
                    created_at,
                    updated_at
                FROM account_funding_addresses
                WHERE id = %s
                """,
                (cursor.lastrowid,),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._build_address(row)

    def upsert_address(
        self,
        *,
        account_id: int,
        network: str,
        address_value: str,
        memo_tag: str,
    ) -> AccountAddress | None:
        if not network and not address_value and not memo_tag:
            self.delete_address(account_id=account_id)
            return None

        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                INSERT INTO account_funding_addresses (
                    account_id,
                    network,
                    address_value,
                    memo_tag
                )
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    network = VALUES(network),
                    address_value = VALUES(address_value),
                    memo_tag = VALUES(memo_tag),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (account_id, network, address_value, memo_tag),
            )
            connection.commit()

            cursor.execute(
                """
                SELECT
                    id,
                    account_id,
                    network,
                    address_value,
                    memo_tag,
                    created_at,
                    updated_at
                FROM account_funding_addresses
                WHERE account_id = %s
                LIMIT 1
                """,
                (account_id,),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._build_address(row)

    def delete_address(self, *, account_id: int) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                DELETE FROM account_funding_addresses
                WHERE account_id = %s
                """,
                (account_id,),
            )
            connection.commit()

    def delete_account(self, *, account_id: int, user_id: int) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                DELETE FROM exchange_accounts
                WHERE id = %s AND user_id = %s
                """,
                (account_id, user_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def list_accounts_with_address_by_user_id(self, user_id: int) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    a.id,
                    a.user_id,
                    a.market_type,
                    a.exchange_code,
                    a.account_name,
                    a.api_key,
                    a.api_secret,
                    a.api_passphrase,
                    a.is_active,
                    a.created_at,
                    a.updated_at,
                    fa.network,
                    fa.address_value,
                    fa.memo_tag,
                    fa.created_at AS address_created_at,
                    fa.updated_at AS address_updated_at
                FROM exchange_accounts AS a
                LEFT JOIN account_funding_addresses AS fa
                    ON fa.account_id = a.id
                WHERE a.user_id = %s
                ORDER BY a.id DESC
                """,
                (user_id,),
            )
            return list(cursor.fetchall())

    def _build_account(self, row: Dict[str, Any]) -> ExchangeAccount:
        return ExchangeAccount(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            market_type=str(row["market_type"]),
            exchange_code=str(row["exchange_code"]),
            account_name=str(row["account_name"]),
            api_key=str(row["api_key"]),
            api_secret=str(row["api_secret"]),
            api_passphrase=str(row["api_passphrase"] or ""),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_address(self, row: Dict[str, Any]) -> AccountAddress:
        return AccountAddress(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            network=str(row["network"] or ""),
            address_value=str(row["address_value"] or ""),
            memo_tag=str(row["memo_tag"] or ""),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


account_repository = MySQLAccountRepository()
