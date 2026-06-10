"""MySQL-backed account repository."""

from __future__ import annotations

from typing import Any, Dict, List

from app.domain.entities import AccountAddress, AutoTransferConfig, ExchangeAccount, StrategyRule, TransferRecord
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
                    a.connection_test_status,
                    a.funding_ratio_percent,
                    a.current_available_amount,
                    a.current_available_synced_at,
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
                    current_available_synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    connection_test_status,
                    funding_ratio_percent,
                    current_available_amount,
                    current_available_synced_at,
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

    def create_transfer_record(
        self,
        *,
        user_id: int,
        from_account_id: int,
        to_account_id: int,
        amount: float,
        reason: str,
        status: str,
        result: str,
    ) -> TransferRecord:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                INSERT INTO account_transfer_records (
                    user_id,
                    from_account_id,
                    to_account_id,
                    amount,
                    reason,
                    status,
                    result
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, from_account_id, to_account_id, amount, reason, status, result),
            )
            connection.commit()

            cursor.execute(
                """
                SELECT
                    id,
                    user_id,
                    from_account_id,
                    to_account_id,
                    amount,
                    reason,
                    status,
                    result,
                    created_at,
                    updated_at
                FROM account_transfer_records
                WHERE id = %s
                LIMIT 1
                """,
                (cursor.lastrowid,),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._build_transfer_record(row)

    def list_transfer_records_by_user_id(self, user_id: int) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    tr.id,
                    tr.user_id,
                    tr.from_account_id,
                    tr.to_account_id,
                    tr.amount,
                    tr.reason,
                    tr.status,
                    tr.result,
                    tr.created_at,
                    tr.updated_at,
                    fa.account_name AS from_account_name,
                    fa.exchange_code AS from_exchange_code,
                    ta.account_name AS to_account_name,
                    ta.exchange_code AS to_exchange_code
                FROM account_transfer_records AS tr
                INNER JOIN exchange_accounts AS fa
                    ON fa.id = tr.from_account_id
                INNER JOIN exchange_accounts AS ta
                    ON ta.id = tr.to_account_id
                WHERE tr.user_id = %s
                ORDER BY tr.id DESC
                """,
                (user_id,),
            )
            return list(cursor.fetchall())

    def get_auto_transfer_config_by_user_id(self, user_id: int) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    user_id,
                    is_enabled,
                    trigger_ratio,
                    created_at,
                    updated_at
                FROM account_auto_transfer_configs
                WHERE user_id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            return cursor.fetchone()

    def upsert_auto_transfer_config(
        self,
        *,
        user_id: int,
        is_enabled: bool,
        trigger_ratio: float,
    ) -> AutoTransferConfig:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                INSERT INTO account_auto_transfer_configs (
                    user_id,
                    is_enabled,
                    trigger_ratio
                )
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    is_enabled = VALUES(is_enabled),
                    trigger_ratio = VALUES(trigger_ratio),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, 1 if is_enabled else 0, trigger_ratio),
            )
            connection.commit()

            cursor.execute(
                """
                SELECT
                    id,
                    user_id,
                    is_enabled,
                    trigger_ratio,
                    created_at,
                    updated_at
                FROM account_auto_transfer_configs
                WHERE user_id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._build_auto_transfer_config(row)

    def list_strategy_rules_by_user_id(self, user_id: int) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    user_id,
                    name,
                    strategy_type,
                    annualized_rate_threshold,
                    spread_rate_threshold,
                    max_spread_rate_threshold,
                    max_pairs,
                    order_amount_usdt,
                    max_position_usdt,
                    order_interval_seconds,
                    is_enabled,
                    created_at,
                    updated_at
                FROM strategy_rules
                WHERE user_id = %s
                ORDER BY id DESC
                """,
                (user_id,),
            )
            return list(cursor.fetchall())

    def get_strategy_rule_by_id(self, rule_id: int, user_id: int) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    user_id,
                    name,
                    strategy_type,
                    annualized_rate_threshold,
                    spread_rate_threshold,
                    max_spread_rate_threshold,
                    max_pairs,
                    order_amount_usdt,
                    max_position_usdt,
                    order_interval_seconds,
                    is_enabled,
                    created_at,
                    updated_at
                FROM strategy_rules
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (rule_id, user_id),
            )
            return cursor.fetchone()

    def create_strategy_rule(
        self,
        *,
        user_id: int,
        name: str,
        strategy_type: str,
        annualized_rate_threshold: float,
        spread_rate_threshold: float,
        max_spread_rate_threshold: float,
        max_pairs: int,
        order_amount_usdt: float,
        max_position_usdt: float,
        order_interval_seconds: int,
        is_enabled: bool,
    ) -> StrategyRule:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                INSERT INTO strategy_rules (
                    user_id,
                    name,
                    strategy_type,
                    annualized_rate_threshold,
                    spread_rate_threshold,
                    max_spread_rate_threshold,
                    max_pairs,
                    order_amount_usdt,
                    max_position_usdt,
                    order_interval_seconds,
                    is_enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    name,
                    strategy_type,
                    annualized_rate_threshold,
                    spread_rate_threshold,
                    max_spread_rate_threshold,
                    max_pairs,
                    order_amount_usdt,
                    max_position_usdt,
                    order_interval_seconds,
                    1 if is_enabled else 0,
                ),
            )
            connection.commit()

            cursor.execute(
                """
                SELECT
                    id,
                    user_id,
                    name,
                    strategy_type,
                    annualized_rate_threshold,
                    spread_rate_threshold,
                    max_spread_rate_threshold,
                    max_pairs,
                    order_amount_usdt,
                    max_position_usdt,
                    order_interval_seconds,
                    is_enabled,
                    created_at,
                    updated_at
                FROM strategy_rules
                WHERE id = %s
                LIMIT 1
                """,
                (cursor.lastrowid,),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._build_strategy_rule(row)

    def update_strategy_rule(
        self,
        *,
        rule_id: int,
        user_id: int,
        name: str,
        strategy_type: str,
        annualized_rate_threshold: float,
        spread_rate_threshold: float,
        max_spread_rate_threshold: float,
        max_pairs: int,
        order_amount_usdt: float,
        max_position_usdt: float,
        order_interval_seconds: int,
        is_enabled: bool,
    ) -> StrategyRule | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                UPDATE strategy_rules
                SET
                    name = %s,
                    strategy_type = %s,
                    annualized_rate_threshold = %s,
                    spread_rate_threshold = %s,
                    max_spread_rate_threshold = %s,
                    max_pairs = %s,
                    order_amount_usdt = %s,
                    max_position_usdt = %s,
                    order_interval_seconds = %s,
                    is_enabled = %s
                WHERE id = %s AND user_id = %s
                """,
                (
                    name,
                    strategy_type,
                    annualized_rate_threshold,
                    spread_rate_threshold,
                    max_spread_rate_threshold,
                    max_pairs,
                    order_amount_usdt,
                    max_position_usdt,
                    order_interval_seconds,
                    1 if is_enabled else 0,
                    rule_id,
                    user_id,
                ),
            )
            connection.commit()

            cursor.execute(
                """
                SELECT
                    id,
                    user_id,
                    name,
                    strategy_type,
                    annualized_rate_threshold,
                    spread_rate_threshold,
                    max_spread_rate_threshold,
                    max_pairs,
                    order_amount_usdt,
                    max_position_usdt,
                    order_interval_seconds,
                    is_enabled,
                    created_at,
                    updated_at
                FROM strategy_rules
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (rule_id, user_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._build_strategy_rule(row)

    def delete_strategy_rule(self, *, rule_id: int, user_id: int) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                DELETE FROM strategy_rules
                WHERE id = %s AND user_id = %s
                """,
                (rule_id, user_id),
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
                    a.connection_test_status,
                    a.funding_ratio_percent,
                    a.current_available_amount,
                    a.current_available_synced_at,
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

    def list_all_accounts_with_address(self) -> List[Dict[str, Any]]:
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
                WHERE a.is_active = 1
                ORDER BY a.id DESC
                """
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
            connection_test_status=str(row.get("connection_test_status") or "untested"),
            funding_ratio_percent=float(row.get("funding_ratio_percent") or 0),
            current_available_amount=float(row.get("current_available_amount") or 0),
            current_available_synced_at=row.get("current_available_synced_at"),
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

    def _build_transfer_record(self, row: Dict[str, Any]) -> TransferRecord:
        return TransferRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            from_account_id=int(row["from_account_id"]),
            to_account_id=int(row["to_account_id"]),
            amount=float(row["amount"]),
            reason=str(row["reason"]),
            status=str(row["status"]),
            result=str(row["result"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_auto_transfer_config(self, row: Dict[str, Any]) -> AutoTransferConfig:
        return AutoTransferConfig(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            is_enabled=bool(row["is_enabled"]),
            trigger_ratio=float(row["trigger_ratio"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_strategy_rule(self, row: Dict[str, Any]) -> StrategyRule:
        return StrategyRule(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            name=str(row["name"]),
            strategy_type=str(row["strategy_type"]),
            annualized_rate_threshold=float(row.get("annualized_rate_threshold") or 0),
            spread_rate_threshold=float(row.get("spread_rate_threshold") or 0),
            max_spread_rate_threshold=float(row.get("max_spread_rate_threshold") or 0),
            max_pairs=int(row.get("max_pairs") or 0),
            order_amount_usdt=float(row.get("order_amount_usdt") or 0),
            max_position_usdt=float(row.get("max_position_usdt") or 0),
            order_interval_seconds=int(row.get("order_interval_seconds") or 0),
            is_enabled=bool(row.get("is_enabled")),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


account_repository = MySQLAccountRepository()
