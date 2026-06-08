"""MySQL connection management and schema bootstrap."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, Optional

import mysql.connector
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
        ]

        with self.connection() as connection:
            cursor = connection.cursor()
            for statement in statements:
                cursor.execute(statement)
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
