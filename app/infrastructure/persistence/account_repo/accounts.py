"""Account, address, and asset-network persistence mixin."""

from __future__ import annotations

from typing import Any, Dict, List

from app.domain.entities import AccountAddress, ExchangeAccount
from app.infrastructure.persistence import mysql_manager


class AccountRepositoryAccountsMixin:
    def list_exchange_asset_networks(self, *, exchange_code: str, asset_code: str) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    exchange_code,
                    asset_code,
                    network_code,
                    network_name,
                    network_id,
                    is_deposit_enabled,
                    is_withdraw_enabled,
                    created_at,
                    updated_at
                FROM exchange_asset_networks
                WHERE exchange_code = %s
                  AND asset_code = %s
                ORDER BY CASE WHEN network_code = 'internal' THEN 1 ELSE 0 END ASC, network_name ASC, network_code ASC
                """,
                (exchange_code, asset_code),
            )
            return list(cursor.fetchall())

    def replace_exchange_asset_networks(
        self,
        *,
        exchange_code: str,
        asset_code: str,
        networks: List[Dict[str, Any]],
    ) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                DELETE FROM exchange_asset_networks
                WHERE exchange_code = %s
                  AND asset_code = %s
                """,
                (exchange_code, asset_code),
            )
            if networks:
                cursor.executemany(
                    """
                    INSERT INTO exchange_asset_networks (
                        exchange_code,
                        asset_code,
                        network_code,
                        network_name,
                        network_id,
                        is_deposit_enabled,
                        is_withdraw_enabled
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            exchange_code,
                            asset_code,
                            str(item.get("network_code") or "").strip(),
                            str(item.get("network_name") or "").strip(),
                            str(item.get("network_id") or "").strip(),
                            1 if bool(item.get("is_deposit_enabled", True)) else 0,
                            1 if bool(item.get("is_withdraw_enabled", True)) else 0,
                        )
                        for item in networks
                        if str(item.get("network_code") or "").strip()
                    ],
                )
            connection.commit()

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
                    a.connection_test_status,
                    a.funding_ratio_percent,
                    a.current_available_amount,
                    a.current_available_synced_at,
                    a.maker_fee_rate,
                    a.taker_fee_rate,
                    a.fee_rate_synced_at,
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

    def get_active_account_with_address_by_id(self, account_id: int, user_id: int) -> Dict[str, Any] | None:
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
                    a.connection_test_status,
                    a.funding_ratio_percent,
                    a.current_available_amount,
                    a.current_available_synced_at,
                    a.maker_fee_rate,
                    a.taker_fee_rate,
                    a.fee_rate_synced_at,
                    a.is_active,
                    a.created_at,
                    a.updated_at,
                    fa.network,
                    fa.address_value,
                    fa.memo_tag,
                    fa.created_at AS address_created_at,
                    fa.updated_at AS address_updated_at
                FROM exchange_accounts AS a
                INNER JOIN users AS u
                    ON u.id = a.user_id
                LEFT JOIN account_funding_addresses AS fa
                    ON fa.account_id = a.id
                WHERE a.id = %s
                  AND a.user_id = %s
                  AND a.is_active = 1
                  AND u.is_active = 1
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
        connection_test_status: str,
        funding_ratio_percent: float = 0,
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
                    api_passphrase,
                    connection_test_status,
                    funding_ratio_percent,
                    current_available_amount,
                    current_available_synced_at,
                    maker_fee_rate,
                    taker_fee_rate,
                    fee_rate_synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    market_type,
                    exchange_code,
                    account_name,
                    api_key,
                    api_secret,
                    api_passphrase,
                    connection_test_status,
                    funding_ratio_percent,
                    0,
                    None,
                    0.05,
                    0.05,
                    None,
                ),
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
                    connection_test_status,
                    funding_ratio_percent,
                    current_available_amount,
                    current_available_synced_at,
                    maker_fee_rate,
                    taker_fee_rate,
                    fee_rate_synced_at,
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
        connection_test_status: str,
        funding_ratio_percent: float = 0,
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
                    api_passphrase = %s,
                    connection_test_status = %s,
                    funding_ratio_percent = %s
                WHERE id = %s AND user_id = %s
                """,
                (
                    market_type,
                    exchange_code,
                    account_name,
                    api_key,
                    api_secret,
                    api_passphrase,
                    connection_test_status,
                    funding_ratio_percent,
                    account_id,
                    user_id,
                ),
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
                    connection_test_status,
                    funding_ratio_percent,
                    current_available_amount,
                    current_available_synced_at,
                    maker_fee_rate,
                    taker_fee_rate,
                    fee_rate_synced_at,
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

    def update_connection_test_status(self, *, account_id: int, user_id: int, status: str) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE exchange_accounts
                SET connection_test_status = %s
                WHERE id = %s AND user_id = %s
                """,
                (status, account_id, user_id),
            )
            connection.commit()
            if cursor.rowcount > 0:
                return True

            verify_cursor = connection.cursor(dictionary=True)
            verify_cursor.execute(
                """
                SELECT id
                FROM exchange_accounts
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (account_id, user_id),
            )
            return verify_cursor.fetchone() is not None

    def update_funding_ratio_percent(self, *, account_id: int, user_id: int, funding_ratio_percent: float) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE exchange_accounts
                SET funding_ratio_percent = %s
                WHERE id = %s AND user_id = %s
                """,
                (funding_ratio_percent, account_id, user_id),
            )
            connection.commit()
            if cursor.rowcount > 0:
                return True

            verify_cursor = connection.cursor(dictionary=True)
            verify_cursor.execute(
                """
                SELECT id
                FROM exchange_accounts
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (account_id, user_id),
            )
            return verify_cursor.fetchone() is not None

    def update_current_available_amount(
        self,
        *,
        account_id: int,
        amount: float,
        synced_at,
    ) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE exchange_accounts
                SET
                    current_available_amount = %s,
                    current_available_synced_at = %s
                WHERE id = %s
                """,
                (amount, synced_at, account_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def update_fee_rates(
        self,
        *,
        account_id: int,
        user_id: int,
        maker_fee_rate: float,
        taker_fee_rate: float,
        synced_at,
    ) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE exchange_accounts
                SET
                    maker_fee_rate = %s,
                    taker_fee_rate = %s,
                    fee_rate_synced_at = %s
                WHERE id = %s AND user_id = %s
                """,
                (maker_fee_rate, taker_fee_rate, synced_at, account_id, user_id),
            )
            connection.commit()
            if cursor.rowcount > 0:
                return True

            verify_cursor = connection.cursor(dictionary=True)
            verify_cursor.execute(
                """
                SELECT id
                FROM exchange_accounts
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (account_id, user_id),
            )
            return verify_cursor.fetchone() is not None
