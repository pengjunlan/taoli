"""MySQL connection management and schema bootstrap."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from typing import Generator, Optional

import mysql.connector
from mysql.connector import Error as MySQLError
from mysql.connector.pooling import MySQLConnectionPool

from app.config import mysql_config


logger = logging.getLogger(__name__)


class MySQLConnectionManager:
    """Owns the MySQL pool and bootstraps required auth tables."""

    def __init__(self) -> None:
        self._pool: Optional[MySQLConnectionPool] = None

    def initialize(self) -> None:
        self._ensure_database()
        self._ensure_pool()
        self._ensure_schema()
        self._sanitize_legacy_account_names()

    def _ensure_database(self) -> None:
        connection = mysql.connector.connect(
            host=mysql_config.host,
            port=mysql_config.port,
            user=mysql_config.user,
            password=mysql_config.password,
            connection_timeout=mysql_config.connection_timeout,
        )
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{mysql_config.database}` "
                f"CHARACTER SET {mysql_config.charset} COLLATE utf8mb4_unicode_ci"
            )
            connection.commit()
        finally:
            connection.close()

    def _ensure_pool(self) -> None:
        if self._pool is not None:
            return

        self._pool = MySQLConnectionPool(
            pool_name=mysql_config.pool_name,
            pool_size=mysql_config.pool_size,
            host=mysql_config.host,
            port=mysql_config.port,
            user=mysql_config.user,
            password=mysql_config.password,
            database=mysql_config.database,
            charset=mysql_config.charset,
            autocommit=False,
            connection_timeout=mysql_config.connection_timeout,
        )

    def _ensure_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(64) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                last_login_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_users_username (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT UNSIGNED NOT NULL,
                session_token_hash CHAR(64) NOT NULL,
                expires_at DATETIME NOT NULL,
                is_revoked TINYINT(1) NOT NULL DEFAULT 0,
                ip_address VARCHAR(64) NULL,
                user_agent VARCHAR(255) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_sessions_token_hash (session_token_hash),
                KEY idx_sessions_user_id (user_id),
                KEY idx_sessions_expires_at (expires_at),
                CONSTRAINT fk_user_sessions_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS auth_login_logs (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT UNSIGNED NULL,
                username VARCHAR(64) NOT NULL,
                is_success TINYINT(1) NOT NULL,
                failure_reason VARCHAR(255) NULL,
                ip_address VARCHAR(64) NULL,
                user_agent VARCHAR(255) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                KEY idx_auth_login_logs_user_id (user_id),
                KEY idx_auth_login_logs_created_at (created_at),
                CONSTRAINT fk_auth_login_logs_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS exchange_accounts (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT UNSIGNED NOT NULL,
                market_type VARCHAR(32) NOT NULL,
                exchange_code VARCHAR(32) NOT NULL,
                account_name VARCHAR(128) NOT NULL,
                api_key VARCHAR(255) NOT NULL,
                api_secret VARCHAR(255) NOT NULL,
                api_passphrase VARCHAR(255) NOT NULL DEFAULT '',
                connection_test_status VARCHAR(32) NOT NULL DEFAULT 'untested',
                funding_ratio_percent DECIMAL(10,2) NOT NULL DEFAULT 0.00,
                current_available_amount DECIMAL(18,8) NOT NULL DEFAULT 0.00000000,
                current_available_synced_at DATETIME NULL,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_exchange_accounts_user_id (user_id),
                KEY idx_exchange_accounts_exchange_code (exchange_code),
                CONSTRAINT fk_exchange_accounts_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS account_funding_addresses (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                account_id BIGINT UNSIGNED NOT NULL,
                network VARCHAR(64) NOT NULL DEFAULT '',
                address_value VARCHAR(255) NOT NULL DEFAULT '',
                memo_tag VARCHAR(120) NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_account_funding_addresses_account_id (account_id),
                CONSTRAINT fk_account_funding_addresses_account
                    FOREIGN KEY (account_id) REFERENCES exchange_accounts (id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS account_transfer_records (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT UNSIGNED NOT NULL,
                from_account_id BIGINT UNSIGNED NOT NULL,
                to_account_id BIGINT UNSIGNED NOT NULL,
                amount DECIMAL(18,2) NOT NULL DEFAULT 0.00,
                reason VARCHAR(255) NOT NULL DEFAULT '手动调拨',
                status VARCHAR(32) NOT NULL DEFAULT 'created',
                result VARCHAR(255) NOT NULL DEFAULT '手动调拨已登记，等待后续执行。',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_account_transfer_records_user_id (user_id),
                KEY idx_account_transfer_records_from_account_id (from_account_id),
                KEY idx_account_transfer_records_to_account_id (to_account_id),
                CONSTRAINT fk_account_transfer_records_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_account_transfer_records_from_account
                    FOREIGN KEY (from_account_id) REFERENCES exchange_accounts (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_account_transfer_records_to_account
                    FOREIGN KEY (to_account_id) REFERENCES exchange_accounts (id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS account_auto_transfer_configs (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT UNSIGNED NOT NULL,
                is_enabled TINYINT(1) NOT NULL DEFAULT 0,
                trigger_ratio DECIMAL(10,4) NOT NULL DEFAULT 0.5000,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_account_auto_transfer_configs_user_id (user_id),
                CONSTRAINT fk_account_auto_transfer_configs_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
        ]

        with self.connection() as connection:
            cursor = connection.cursor()
            for statement in statements:
                cursor.execute(statement)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'exchange_accounts'
                  AND COLUMN_NAME = 'connection_test_status'
                """,
                (mysql_config.database,),
            )
            has_connection_test_status = int(cursor.fetchone()[0]) > 0
            if not has_connection_test_status:
                cursor.execute(
                    """
                    ALTER TABLE exchange_accounts
                    ADD COLUMN connection_test_status VARCHAR(32) NOT NULL DEFAULT 'untested'
                    AFTER api_passphrase
                    """
                )
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'exchange_accounts'
                  AND COLUMN_NAME = 'funding_ratio_percent'
                """,
                (mysql_config.database,),
            )
            has_funding_ratio_percent = int(cursor.fetchone()[0]) > 0
            if not has_funding_ratio_percent:
                cursor.execute(
                    """
                    ALTER TABLE exchange_accounts
                    ADD COLUMN funding_ratio_percent DECIMAL(10,2) NOT NULL DEFAULT 0.00
                    AFTER connection_test_status
                    """
                )
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'exchange_accounts'
                  AND COLUMN_NAME = 'current_available_amount'
                """,
                (mysql_config.database,),
            )
            has_current_available_amount = int(cursor.fetchone()[0]) > 0
            if not has_current_available_amount:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE exchange_accounts
                        ADD COLUMN current_available_amount DECIMAL(18,8) NOT NULL DEFAULT 0.00000000
                        AFTER funding_ratio_percent
                        """
                    )
                except MySQLError as exc:
                    if "Duplicate column name" not in str(exc):
                        raise
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'exchange_accounts'
                  AND COLUMN_NAME = 'current_available_synced_at'
                """,
                (mysql_config.database,),
            )
            has_current_available_synced_at = int(cursor.fetchone()[0]) > 0
            if not has_current_available_synced_at:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE exchange_accounts
                        ADD COLUMN current_available_synced_at DATETIME NULL
                        AFTER current_available_amount
                        """
                    )
                except MySQLError as exc:
                    if "Duplicate column name" not in str(exc):
                        raise
            connection.commit()

    def _sanitize_legacy_account_names(self) -> None:
        with self.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, account_name
                FROM exchange_accounts
                WHERE account_name REGEXP %s
                """,
                (r" U[0-9]+$",),
            )
            rows = list(cursor.fetchall())
            if not rows:
                return

            update_cursor = connection.cursor()
            for row in rows:
                account_name = str(row["account_name"])
                sanitized_name = re.sub(r"\s+U\d+$", "", account_name).strip()
                if sanitized_name == account_name or not sanitized_name:
                    continue

                update_cursor.execute(
                    """
                    UPDATE exchange_accounts
                    SET account_name = %s
                    WHERE id = %s
                    """,
                    (sanitized_name, int(row["id"])),
                )
            connection.commit()

    @contextmanager
    def connection(self) -> Generator[mysql.connector.MySQLConnection, None, None]:
        if self._pool is None:
            self.initialize()

        assert self._pool is not None
        connection = self._pool.get_connection()
        try:
            yield connection
        finally:
            connection.close()


mysql_manager = MySQLConnectionManager()
