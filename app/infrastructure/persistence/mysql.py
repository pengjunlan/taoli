"""MySQL connection management and schema bootstrap."""

from __future__ import annotations

import logging
import re
import threading
from contextlib import contextmanager
from typing import Generator, Optional

import mysql.connector
from mysql.connector import Error as MySQLError
from mysql.connector.pooling import MySQLConnectionPool

from app.config import mysql_config
from app.infrastructure.persistence.mysql_bootstrap import ensure_database
from app.infrastructure.persistence.mysql_pool import create_pool


logger = logging.getLogger(__name__)


class MySQLConnectionManager:
    """Owns the MySQL pool and bootstraps required auth tables."""

    def __init__(self) -> None:
        self._pool: Optional[MySQLConnectionPool] = None
        self._initialized = False
        self._initializing = False
        self._init_lock = threading.Lock()

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._initializing = True
            try:
                logger.info("MySQL init step start: ensure_database")
                self._ensure_database()
                logger.info("MySQL init step done: ensure_database")
                logger.info("MySQL init step start: ensure_pool")
                self._ensure_pool()
                logger.info("MySQL init step done: ensure_pool")
                logger.info("MySQL init step start: ensure_schema")
                self._ensure_schema()
                logger.info("MySQL init step done: ensure_schema")
                logger.info("MySQL init step start: sanitize_legacy_account_names")
                self._sanitize_legacy_account_names()
                logger.info("MySQL init step done: sanitize_legacy_account_names")
                self._initialized = True
            finally:
                self._initializing = False

    def _ensure_database(self) -> None:
        ensure_database()

    def _ensure_pool(self) -> None:
        if self._pool is not None:
            return

        self._pool = create_pool()

    def _ensure_schema(self) -> None:
        connection = mysql.connector.connect(
            host=mysql_config.host,
            port=mysql_config.port,
            user=mysql_config.user,
            password=mysql_config.password,
            database=mysql_config.database,
            charset=mysql_config.charset,
            autocommit=False,
            connection_timeout=mysql_config.connection_timeout,
        )
        try:
            with self.advisory_lock(
                connection,
                f"{mysql_config.database}.schema_bootstrap",
                timeout_seconds=60,
            ):
                self._ensure_schema_with_connection(connection)
        finally:
            connection.close()

    def _ensure_schema_with_connection(
        self,
        connection: mysql.connector.MySQLConnection,
    ) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(64) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                is_admin TINYINT(1) NOT NULL DEFAULT 0,
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
                maker_fee_rate DECIMAL(10,6) NOT NULL DEFAULT 0.050000,
                taker_fee_rate DECIMAL(10,6) NOT NULL DEFAULT 0.050000,
                fee_rate_synced_at DATETIME NULL,
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
            CREATE TABLE IF NOT EXISTS exchange_asset_networks (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                exchange_code VARCHAR(32) NOT NULL,
                asset_code VARCHAR(32) NOT NULL DEFAULT 'USDT',
                network_code VARCHAR(64) NOT NULL,
                network_name VARCHAR(128) NOT NULL DEFAULT '',
                network_id VARCHAR(128) NOT NULL DEFAULT '',
                is_deposit_enabled TINYINT(1) NOT NULL DEFAULT 1,
                is_withdraw_enabled TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_exchange_asset_networks_exchange_asset_network (exchange_code, asset_code, network_code),
                KEY idx_exchange_asset_networks_exchange_asset (exchange_code, asset_code)
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
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                execute_status VARCHAR(32) NOT NULL DEFAULT 'pending_execute',
                result_status VARCHAR(32) NOT NULL DEFAULT 'none',
                failure_type VARCHAR(32) NOT NULL DEFAULT '',
                failure_reason VARCHAR(255) NOT NULL DEFAULT '',
                config_fingerprint VARCHAR(255) NOT NULL DEFAULT '',
                is_worker_enabled TINYINT(1) NOT NULL DEFAULT 0,
                result VARCHAR(255) NOT NULL DEFAULT '手动调拨已登记，等待后续执行。',
                actual_to_network VARCHAR(64) NOT NULL DEFAULT '',
                actual_to_address_value VARCHAR(255) NOT NULL DEFAULT '',
                actual_to_memo_tag VARCHAR(120) NOT NULL DEFAULT '',
                execution_checkpoint VARCHAR(64) NOT NULL DEFAULT '',
                execution_reference VARCHAR(255) NOT NULL DEFAULT '',
                execution_payload LONGTEXT NULL,
                processed_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_account_transfer_records_user_id (user_id),
                KEY idx_account_transfer_records_worker_status (is_worker_enabled, execute_status),
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
            """
            CREATE TABLE IF NOT EXISTS strategy_rules (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT UNSIGNED NOT NULL,
                name VARCHAR(128) NOT NULL,
                strategy_type VARCHAR(32) NOT NULL,
                annualized_rate_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                min_net_funding_rate_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                spread_rate_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                open_spread_rate_max_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                min_close_spread_rate_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                max_spread_rate_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                max_pairs INT NOT NULL DEFAULT 1,
                order_amount_usdt DECIMAL(18,2) NOT NULL DEFAULT 0.00,
                max_position_usdt DECIMAL(18,2) NOT NULL DEFAULT 0.00,
                order_interval_seconds INT NOT NULL DEFAULT 0,
                split_order_amount_usdt DECIMAL(18,2) NOT NULL DEFAULT 0.00,
                funding_open_window_start_minutes INT NOT NULL DEFAULT 0,
                funding_open_window_end_minutes INT NOT NULL DEFAULT 0,
                funding_settlement_skew_minutes INT NOT NULL DEFAULT 0,
                funding_spread_resonance_min DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                net_spread_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                funding_carry_min DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                max_funding_cost DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                min_net_profit_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                take_profit_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                drawdown_add_step_percent DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                max_hold_minutes INT NOT NULL DEFAULT 0,
                close_interval_seconds INT NOT NULL DEFAULT 0,
                close_batch_count INT NOT NULL DEFAULT 0,
                close_batch_ratio_percent DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                single_leg_timeout_seconds INT NOT NULL DEFAULT 0,
                is_enabled TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_strategy_rules_user_id (user_id),
                KEY idx_strategy_rules_type (strategy_type),
                CONSTRAINT fk_strategy_rules_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS exchange_markets (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                exchange_code VARCHAR(32) NOT NULL,
                market_type VARCHAR(32) NOT NULL,
                symbol VARCHAR(128) NOT NULL,
                symbol_normalized VARCHAR(128) NOT NULL,
                base_asset VARCHAR(64) NOT NULL,
                quote_asset VARCHAR(64) NOT NULL,
                settle_asset VARCHAR(64) NOT NULL DEFAULT '',
                is_contract TINYINT(1) NOT NULL DEFAULT 0,
                is_linear TINYINT(1) NOT NULL DEFAULT 0,
                contract_size DECIMAL(18,8) NOT NULL DEFAULT 0.00000000,
                price_precision DECIMAL(18,8) NOT NULL DEFAULT 0.00000000,
                amount_precision DECIMAL(18,8) NOT NULL DEFAULT 0.00000000,
                min_amount DECIMAL(18,8) NOT NULL DEFAULT 0.00000000,
                supports_funding TINYINT(1) NOT NULL DEFAULT 0,
                supports_ws TINYINT(1) NOT NULL DEFAULT 1,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_exchange_markets_unique (exchange_code, market_type, symbol),
                KEY idx_exchange_markets_symbol_normalized (symbol_normalized),
                KEY idx_exchange_markets_exchange_market (exchange_code, market_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS exchange_market_pairs (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                pair_type VARCHAR(32) NOT NULL,
                pair_key VARCHAR(255) NOT NULL,
                left_exchange_code VARCHAR(32) NOT NULL,
                right_exchange_code VARCHAR(32) NOT NULL,
                left_market_type VARCHAR(32) NOT NULL,
                right_market_type VARCHAR(32) NOT NULL,
                symbol_normalized VARCHAR(128) NOT NULL,
                left_symbol VARCHAR(128) NOT NULL,
                right_symbol VARCHAR(128) NOT NULL,
                base_asset VARCHAR(64) NOT NULL,
                quote_asset VARCHAR(64) NOT NULL,
                settle_asset VARCHAR(64) NOT NULL DEFAULT '',
                match_mode VARCHAR(32) NOT NULL DEFAULT 'auto',
                pair_reason VARCHAR(255) NOT NULL DEFAULT '',
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                generated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_exchange_market_pairs_pair_key (pair_key),
                KEY idx_exchange_market_pairs_type (pair_type),
                KEY idx_exchange_market_pairs_symbol (symbol_normalized)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS arbitrage_executions (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT UNSIGNED NOT NULL,
                strategy_type VARCHAR(32) NOT NULL,
                strategy_rule_id BIGINT UNSIGNED NULL,
                strategy_rule_name VARCHAR(128) NOT NULL DEFAULT '',
                source_execution_id BIGINT UNSIGNED NULL,
                pair_key VARCHAR(255) NOT NULL DEFAULT '',
                action VARCHAR(16) NOT NULL DEFAULT 'open',
                symbol VARCHAR(128) NOT NULL,
                base_asset VARCHAR(64) NOT NULL DEFAULT '',
                quote_asset VARCHAR(64) NOT NULL DEFAULT 'USDT',
                left_exchange_code VARCHAR(32) NOT NULL DEFAULT '',
                right_exchange_code VARCHAR(32) NOT NULL DEFAULT '',
                left_market_type VARCHAR(32) NOT NULL DEFAULT '',
                right_market_type VARCHAR(32) NOT NULL DEFAULT '',
                left_symbol VARCHAR(128) NOT NULL DEFAULT '',
                right_symbol VARCHAR(128) NOT NULL DEFAULT '',
                planned_order_amount_usdt DECIMAL(18,2) NOT NULL DEFAULT 0.00,
                max_position_usdt DECIMAL(18,2) NOT NULL DEFAULT 0.00,
                trigger_metric_primary VARCHAR(64) NOT NULL DEFAULT '',
                trigger_metric_secondary VARCHAR(64) NOT NULL DEFAULT '',
                trigger_metric_risk VARCHAR(64) NOT NULL DEFAULT '',
                trigger_reason VARCHAR(255) NOT NULL DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_arbitrage_executions_user_status (user_id, status),
                KEY idx_arbitrage_executions_rule_pair (strategy_rule_id, pair_key, status),
                KEY idx_arbitrage_executions_strategy_type (strategy_type),
                KEY idx_arbitrage_executions_symbol (symbol),
                CONSTRAINT fk_arbitrage_executions_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS arbitrage_order_legs (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                execution_id BIGINT UNSIGNED NOT NULL,
                user_id BIGINT UNSIGNED NOT NULL,
                exchange_account_id BIGINT UNSIGNED NULL,
                leg_role VARCHAR(16) NOT NULL DEFAULT 'unknown',
                position_side VARCHAR(16) NOT NULL DEFAULT 'net',
                exchange_code VARCHAR(32) NOT NULL DEFAULT '',
                market_type VARCHAR(32) NOT NULL DEFAULT '',
                symbol VARCHAR(128) NOT NULL DEFAULT '',
                side VARCHAR(16) NOT NULL DEFAULT '',
                order_type VARCHAR(16) NOT NULL DEFAULT 'market',
                client_order_id VARCHAR(128) NULL,
                exchange_order_id VARCHAR(128) NULL,
                requested_price DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                requested_quantity DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                requested_value_usdt DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                retry_count INT NOT NULL DEFAULT 0,
                average_fill_price DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                filled_quantity DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                filled_value_usdt DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                status_message VARCHAR(255) NOT NULL DEFAULT '',
                submitted_at DATETIME NULL,
                acknowledged_at DATETIME NULL,
                last_retry_at DATETIME NULL,
                closed_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_arbitrage_order_legs_execution_id (execution_id),
                KEY idx_arbitrage_order_legs_user_status (user_id, status),
                KEY idx_arbitrage_order_legs_exchange_order_id (exchange_order_id),
                CONSTRAINT fk_arbitrage_order_legs_execution
                    FOREIGN KEY (execution_id) REFERENCES arbitrage_executions (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_arbitrage_order_legs_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_arbitrage_order_legs_account
                    FOREIGN KEY (exchange_account_id) REFERENCES exchange_accounts (id)
                    ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS arbitrage_fill_records (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                execution_id BIGINT UNSIGNED NOT NULL,
                order_leg_id BIGINT UNSIGNED NOT NULL,
                user_id BIGINT UNSIGNED NOT NULL,
                exchange_account_id BIGINT UNSIGNED NULL,
                exchange_code VARCHAR(32) NOT NULL DEFAULT '',
                market_type VARCHAR(32) NOT NULL DEFAULT '',
                symbol VARCHAR(128) NOT NULL DEFAULT '',
                position_side VARCHAR(16) NOT NULL DEFAULT 'net',
                side VARCHAR(16) NOT NULL DEFAULT '',
                exchange_fill_id VARCHAR(128) NULL,
                fill_price DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                fill_quantity DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                fill_value_usdt DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                fee_amount DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                fee_asset VARCHAR(32) NOT NULL DEFAULT '',
                liquidity VARCHAR(16) NOT NULL DEFAULT '',
                filled_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                KEY idx_arbitrage_fill_records_execution_id (execution_id),
                KEY idx_arbitrage_fill_records_order_leg_id (order_leg_id),
                KEY idx_arbitrage_fill_records_user_id (user_id),
                KEY idx_arbitrage_fill_records_symbol (symbol),
                CONSTRAINT fk_arbitrage_fill_records_execution
                    FOREIGN KEY (execution_id) REFERENCES arbitrage_executions (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_arbitrage_fill_records_order_leg
                    FOREIGN KEY (order_leg_id) REFERENCES arbitrage_order_legs (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_arbitrage_fill_records_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_arbitrage_fill_records_account
                    FOREIGN KEY (exchange_account_id) REFERENCES exchange_accounts (id)
                    ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS arbitrage_positions (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT UNSIGNED NOT NULL,
                exchange_account_id BIGINT UNSIGNED NULL,
                exchange_code VARCHAR(32) NOT NULL DEFAULT '',
                market_type VARCHAR(32) NOT NULL DEFAULT '',
                symbol VARCHAR(128) NOT NULL DEFAULT '',
                base_asset VARCHAR(64) NOT NULL DEFAULT '',
                quote_asset VARCHAR(64) NOT NULL DEFAULT 'USDT',
                position_side VARCHAR(16) NOT NULL DEFAULT 'net',
                quantity DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                avg_entry_price DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                mark_price DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                market_value_usdt DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                realized_pnl_usdt DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                unrealized_pnl_usdt DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                opened_by_execution_id BIGINT UNSIGNED NULL,
                last_order_leg_id BIGINT UNSIGNED NULL,
                last_fill_id BIGINT UNSIGNED NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'open',
                last_synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_arbitrage_positions_account_symbol_side (
                    exchange_account_id,
                    market_type,
                    symbol,
                    position_side
                ),
                KEY idx_arbitrage_positions_user_status (user_id, status),
                KEY idx_arbitrage_positions_symbol (symbol),
                CONSTRAINT fk_arbitrage_positions_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_arbitrage_positions_account
                    FOREIGN KEY (exchange_account_id) REFERENCES exchange_accounts (id)
                    ON DELETE SET NULL,
                CONSTRAINT fk_arbitrage_positions_execution
                    FOREIGN KEY (opened_by_execution_id) REFERENCES arbitrage_executions (id)
                    ON DELETE SET NULL,
                CONSTRAINT fk_arbitrage_positions_order_leg
                    FOREIGN KEY (last_order_leg_id) REFERENCES arbitrage_order_legs (id)
                    ON DELETE SET NULL,
                CONSTRAINT fk_arbitrage_positions_fill
                    FOREIGN KEY (last_fill_id) REFERENCES arbitrage_fill_records (id)
                    ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS arbitrage_funding_fee_receipts (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                execution_id BIGINT UNSIGNED NOT NULL,
                order_leg_id BIGINT UNSIGNED NULL,
                user_id BIGINT UNSIGNED NOT NULL,
                exchange_account_id BIGINT UNSIGNED NULL,
                exchange_code VARCHAR(32) NOT NULL DEFAULT '',
                market_type VARCHAR(32) NOT NULL DEFAULT '',
                symbol VARCHAR(128) NOT NULL DEFAULT '',
                position_side VARCHAR(16) NOT NULL DEFAULT '',
                asset_code VARCHAR(32) NOT NULL DEFAULT '',
                fee_amount DECIMAL(28,12) NOT NULL DEFAULT 0.000000000000,
                exchange_record_id VARCHAR(128) NOT NULL DEFAULT '',
                settled_at DATETIME NULL,
                raw_payload LONGTEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_arbitrage_funding_receipt_record (
                    execution_id,
                    exchange_account_id,
                    exchange_record_id
                ),
                KEY idx_arbitrage_funding_fee_receipts_execution_id (execution_id),
                KEY idx_arbitrage_funding_fee_receipts_user_id (user_id),
                CONSTRAINT fk_arbitrage_funding_fee_receipts_execution
                    FOREIGN KEY (execution_id) REFERENCES arbitrage_executions (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_arbitrage_funding_fee_receipts_order_leg
                    FOREIGN KEY (order_leg_id) REFERENCES arbitrage_order_legs (id)
                    ON DELETE SET NULL,
                CONSTRAINT fk_arbitrage_funding_fee_receipts_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_arbitrage_funding_fee_receipts_account
                    FOREIGN KEY (exchange_account_id) REFERENCES exchange_accounts (id)
                    ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS opportunity_snapshots (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT UNSIGNED NOT NULL,
                channel VARCHAR(32) NOT NULL,
                snapshot_json LONGTEXT NOT NULL,
                row_count INT NOT NULL DEFAULT 0,
                generated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_opportunity_snapshots_user_channel (user_id, channel),
                KEY idx_opportunity_snapshots_channel (channel),
                CONSTRAINT fk_opportunity_snapshots_user
                    FOREIGN KEY (user_id) REFERENCES users (id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS public_opportunity_snapshots (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                channel VARCHAR(32) NOT NULL,
                snapshot_json LONGTEXT NOT NULL,
                row_count INT NOT NULL DEFAULT 0,
                generated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_public_opportunity_snapshots_channel (channel)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS system_exchange_configs (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                exchange_code VARCHAR(32) NOT NULL,
                is_enabled TINYINT(1) NOT NULL DEFAULT 1,
                use_public_api TINYINT(1) NOT NULL DEFAULT 1,
                api_key VARCHAR(255) NOT NULL DEFAULT '',
                api_secret VARCHAR(255) NOT NULL DEFAULT '',
                api_passphrase VARCHAR(255) NOT NULL DEFAULT '',
                remark VARCHAR(255) NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_system_exchange_configs_exchange_code (exchange_code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS system_runtime_configs (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                config_key VARCHAR(128) NOT NULL,
                config_value LONGTEXT NOT NULL,
                remark VARCHAR(255) NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_system_runtime_configs_key (config_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
        ]

        cursor = connection.cursor()
        try:
            for statement in statements:
                cursor.execute(statement)
            self._migrate_legacy_public_opportunity_snapshots(cursor)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'users'
                  AND COLUMN_NAME = 'is_admin'
                """,
                (mysql_config.database,),
            )
            has_users_is_admin = int(cursor.fetchone()[0]) > 0
            if not has_users_is_admin:
                cursor.execute(
                    """
                    ALTER TABLE users
                    ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0
                    AFTER is_active
                    """
                )
            cursor.execute(
                """
                UPDATE users
                SET is_admin = 1
                WHERE id = (
                    SELECT earliest_user_id
                    FROM (
                        SELECT MIN(id) AS earliest_user_id
                        FROM users
                    ) AS first_user
                )
                """
            )
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
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'account_transfer_records'
                  AND COLUMN_NAME = 'is_worker_enabled'
                """,
                (mysql_config.database,),
            )
            has_transfer_worker_enabled = int(cursor.fetchone()[0]) > 0
            if not has_transfer_worker_enabled:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE account_transfer_records
                        ADD COLUMN is_worker_enabled TINYINT(1) NOT NULL DEFAULT 0
                        AFTER status
                        """
                    )
                except MySQLError as exc:
                    if "Duplicate column name" not in str(exc):
                        raise
                try:
                    cursor.execute(
                        """
                        ALTER TABLE account_transfer_records
                        ADD KEY idx_account_transfer_records_worker_status (is_worker_enabled, status)
                        """
                    )
                except MySQLError as exc:
                    if "Duplicate key name" not in str(exc):
                        raise
            cursor.execute(
                """
                SELECT COLUMN_DEFAULT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'account_transfer_records'
                  AND COLUMN_NAME = 'status'
                LIMIT 1
                """,
                (mysql_config.database,),
            )
            transfer_status_default_row = cursor.fetchone()
            transfer_status_default = str(transfer_status_default_row[0] or "").strip().lower() if transfer_status_default_row else ""
            if transfer_status_default != "pending":
                try:
                    cursor.execute(
                        """
                        ALTER TABLE account_transfer_records
                        ALTER COLUMN status SET DEFAULT 'pending'
                        """
                    )
                except MySQLError as exc:
                    if "You have an error in your SQL syntax" in str(exc):
                        cursor.execute(
                            """
                            ALTER TABLE account_transfer_records
                            MODIFY COLUMN status VARCHAR(32) NOT NULL DEFAULT 'pending'
                            """
                        )
                    else:
                        raise
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="execute_status",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN execute_status VARCHAR(32) NOT NULL DEFAULT 'pending_execute'
                    AFTER status
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="result_status",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN result_status VARCHAR(32) NOT NULL DEFAULT 'none'
                    AFTER execute_status
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="failure_type",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN failure_type VARCHAR(32) NOT NULL DEFAULT ''
                    AFTER result_status
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="failure_reason",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN failure_reason VARCHAR(255) NOT NULL DEFAULT ''
                    AFTER failure_type
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="config_fingerprint",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN config_fingerprint VARCHAR(255) NOT NULL DEFAULT ''
                    AFTER failure_reason
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="processed_at",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN processed_at DATETIME NULL
                    AFTER result
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="actual_to_network",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN actual_to_network VARCHAR(64) NOT NULL DEFAULT ''
                    AFTER result
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="actual_to_address_value",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN actual_to_address_value VARCHAR(255) NOT NULL DEFAULT ''
                    AFTER actual_to_network
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="actual_to_memo_tag",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN actual_to_memo_tag VARCHAR(120) NOT NULL DEFAULT ''
                    AFTER actual_to_address_value
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="execution_checkpoint",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN execution_checkpoint VARCHAR(64) NOT NULL DEFAULT ''
                    AFTER actual_to_memo_tag
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="execution_reference",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN execution_reference VARCHAR(255) NOT NULL DEFAULT ''
                    AFTER execution_checkpoint
                """,
            )
            self._ensure_column(
                cursor,
                table_name="account_transfer_records",
                column_name="execution_payload",
                ddl="""
                    ALTER TABLE account_transfer_records
                    ADD COLUMN execution_payload LONGTEXT NULL
                    AFTER execution_reference
                """,
            )
            cursor.execute(
                """
                UPDATE account_transfer_records
                SET
                    execute_status = CASE
                        WHEN status IN ('pending', 'created') THEN 'pending_execute'
                        WHEN status = 'processing' THEN 'executing'
                        ELSE 'processed'
                    END,
                    result_status = CASE
                        WHEN status = 'success' THEN 'success'
                        WHEN status = 'failed' THEN 'failed'
                        WHEN status = 'ignored' THEN 'ignored'
                        ELSE 'none'
                    END,
                    failure_type = CASE
                        WHEN status = 'failed' AND failure_type = '' THEN 'temporary'
                        ELSE failure_type
                    END,
                    failure_reason = CASE
                        WHEN status = 'failed' AND failure_reason = '' THEN result
                        ELSE failure_reason
                    END,
                    processed_at = CASE
                        WHEN status IN ('success', 'failed', 'ignored') AND processed_at IS NULL THEN updated_at
                        ELSE processed_at
                    END
                """
            )
            try:
                cursor.execute(
                    """
                    ALTER TABLE account_transfer_records
                    DROP KEY idx_account_transfer_records_worker_status
                    """
                )
            except MySQLError as exc:
                if "Can't DROP" not in str(exc) and "check that column/key exists" not in str(exc):
                    raise
            try:
                cursor.execute(
                    """
                    ALTER TABLE account_transfer_records
                    ADD KEY idx_account_transfer_records_worker_status (is_worker_enabled, execute_status)
                    """
                )
            except MySQLError as exc:
                if "Duplicate key name" not in str(exc):
                    raise
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'strategy_rules'
                  AND COLUMN_NAME = 'max_position_usdt'
                """,
                (mysql_config.database,),
            )
            has_max_position_usdt = int(cursor.fetchone()[0]) > 0
            if not has_max_position_usdt:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE strategy_rules
                        ADD COLUMN max_position_usdt DECIMAL(18,2) NOT NULL DEFAULT 0.00
                        AFTER order_amount_usdt
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
                  AND TABLE_NAME = 'strategy_rules'
                  AND COLUMN_NAME = 'min_net_funding_rate_threshold'
                """,
                (mysql_config.database,),
            )
            has_min_net_funding_rate_threshold = int(cursor.fetchone()[0]) > 0
            added_min_net_funding_rate_threshold = False
            if not has_min_net_funding_rate_threshold:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE strategy_rules
                        ADD COLUMN min_net_funding_rate_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                        AFTER annualized_rate_threshold
                        """
                    )
                    added_min_net_funding_rate_threshold = True
                except MySQLError as exc:
                    if "Duplicate column name" not in str(exc):
                        raise
            if added_min_net_funding_rate_threshold:
                cursor.execute(
                    """
                    UPDATE strategy_rules
                    SET annualized_rate_threshold = ROUND(annualized_rate_threshold / 1095, 4)
                    WHERE strategy_type = 'funding'
                      AND annualized_rate_threshold > 0
                    """
                )
            cursor.execute(
                """
                UPDATE strategy_rules
                SET min_net_funding_rate_threshold = annualized_rate_threshold
                WHERE strategy_type = 'funding'
                  AND min_net_funding_rate_threshold <= 0
                  AND annualized_rate_threshold > 0
                """
            )
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'strategy_rules'
                  AND COLUMN_NAME = 'max_spread_rate_threshold'
                """,
                (mysql_config.database,),
            )
            has_max_spread_rate_threshold = int(cursor.fetchone()[0]) > 0
            if not has_max_spread_rate_threshold:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE strategy_rules
                        ADD COLUMN max_spread_rate_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                        AFTER spread_rate_threshold
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
                  AND TABLE_NAME = 'strategy_rules'
                  AND COLUMN_NAME = 'min_close_spread_rate_threshold'
                """,
                (mysql_config.database,),
            )
            has_min_close_spread_rate_threshold = int(cursor.fetchone()[0]) > 0
            if not has_min_close_spread_rate_threshold:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE strategy_rules
                        ADD COLUMN min_close_spread_rate_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                        AFTER spread_rate_threshold
                        """
                    )
                except MySQLError as exc:
                    if "Duplicate column name" not in str(exc):
                        raise
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="open_spread_rate_max_threshold",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN open_spread_rate_max_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                    AFTER spread_rate_threshold
                """,
            )
            cursor.execute(
                """
                UPDATE strategy_rules
                SET open_spread_rate_max_threshold = max_spread_rate_threshold
                WHERE strategy_type = 'spread'
                  AND open_spread_rate_max_threshold <= 0
                  AND max_spread_rate_threshold > 0
                """
            )
            cursor.execute(
                """
                UPDATE strategy_rules
                SET min_close_spread_rate_threshold = spread_rate_threshold
                WHERE strategy_type = 'spread'
                  AND min_close_spread_rate_threshold <= 0
                  AND spread_rate_threshold > 0
                """
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="funding_open_window_start_minutes",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN funding_open_window_start_minutes INT NOT NULL DEFAULT 0
                    AFTER order_interval_seconds
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="funding_open_window_end_minutes",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN funding_open_window_end_minutes INT NOT NULL DEFAULT 0
                    AFTER funding_open_window_start_minutes
                """,
            )
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'strategy_rules'
                  AND COLUMN_NAME = 'funding_settlement_skew_minutes'
                """,
                (mysql_config.database,),
            )
            has_funding_settlement_skew_minutes = int(cursor.fetchone()[0]) > 0
            if not has_funding_settlement_skew_minutes:
                cursor.execute(
                    """
                    ALTER TABLE strategy_rules
                    ADD COLUMN funding_settlement_skew_minutes INT NOT NULL DEFAULT 0
                    AFTER funding_open_window_end_minutes
                    """
                )
                cursor.execute(
                    """
                    UPDATE strategy_rules
                    SET funding_settlement_skew_minutes = %s
                    WHERE strategy_type = 'funding'
                    """,
                    (int(strategy_risk_config.max_funding_settlement_skew_minutes or 0),),
                )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="funding_spread_resonance_min",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN funding_spread_resonance_min DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                    AFTER funding_open_window_end_minutes
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="net_spread_threshold",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN net_spread_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                    AFTER funding_spread_resonance_min
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="funding_carry_min",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN funding_carry_min DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                    AFTER net_spread_threshold
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="max_funding_cost",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN max_funding_cost DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                    AFTER funding_carry_min
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="min_net_profit_threshold",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN min_net_profit_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                    AFTER max_funding_cost
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="take_profit_threshold",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN take_profit_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                    AFTER min_net_profit_threshold
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="drawdown_add_step_percent",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN drawdown_add_step_percent DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                    AFTER take_profit_threshold
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="max_hold_minutes",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN max_hold_minutes INT NOT NULL DEFAULT 0
                    AFTER take_profit_threshold
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="split_order_amount_usdt",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN split_order_amount_usdt DECIMAL(18,2) NOT NULL DEFAULT 0.00
                    AFTER order_interval_seconds
                """,
            )
            cursor.execute(
                """
                UPDATE strategy_rules
                SET split_order_amount_usdt = order_amount_usdt
                WHERE split_order_amount_usdt <= 0
                  AND order_amount_usdt > 0
                """
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="close_interval_seconds",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN close_interval_seconds INT NOT NULL DEFAULT 0
                    AFTER max_hold_minutes
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="close_batch_count",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN close_batch_count INT NOT NULL DEFAULT 0
                    AFTER close_interval_seconds
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="single_leg_timeout_seconds",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN single_leg_timeout_seconds INT NOT NULL DEFAULT 0
                    AFTER close_batch_count
                """,
            )
            self._ensure_column(
                cursor,
                table_name="strategy_rules",
                column_name="close_batch_ratio_percent",
                ddl="""
                    ALTER TABLE strategy_rules
                    ADD COLUMN close_batch_ratio_percent DECIMAL(10,4) NOT NULL DEFAULT 0.0000
                    AFTER close_batch_count
                """,
            )
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'arbitrage_executions'
                  AND COLUMN_NAME = 'source_execution_id'
                """,
                (mysql_config.database,),
            )
            has_arbitrage_execution_source_execution_id = int(cursor.fetchone()[0]) > 0
            if not has_arbitrage_execution_source_execution_id:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE arbitrage_executions
                        ADD COLUMN source_execution_id BIGINT UNSIGNED NULL
                        AFTER strategy_rule_name
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
                  AND TABLE_NAME = 'arbitrage_executions'
                  AND COLUMN_NAME = 'pair_key'
                """,
                (mysql_config.database,),
            )
            has_arbitrage_execution_pair_key = int(cursor.fetchone()[0]) > 0
            if not has_arbitrage_execution_pair_key:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE arbitrage_executions
                        ADD COLUMN pair_key VARCHAR(255) NOT NULL DEFAULT ''
                        AFTER strategy_rule_name
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
                  AND TABLE_NAME = 'arbitrage_executions'
                  AND COLUMN_NAME = 'action'
                """,
                (mysql_config.database,),
            )
            has_arbitrage_execution_action = int(cursor.fetchone()[0]) > 0
            if not has_arbitrage_execution_action:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE arbitrage_executions
                        ADD COLUMN action VARCHAR(16) NOT NULL DEFAULT 'open'
                        AFTER pair_key
                        """
                    )
                except MySQLError as exc:
                    if "Duplicate column name" not in str(exc):
                        raise
            try:
                cursor.execute(
                    """
                    ALTER TABLE arbitrage_executions
                    ADD KEY idx_arbitrage_executions_rule_pair (strategy_rule_id, pair_key, status)
                    """
                )
            except MySQLError as exc:
                if "Duplicate key name" not in str(exc):
                    raise
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'arbitrage_order_legs'
                  AND COLUMN_NAME = 'retry_count'
                """,
                (mysql_config.database,),
            )
            has_arbitrage_order_retry_count = int(cursor.fetchone()[0]) > 0
            if not has_arbitrage_order_retry_count:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE arbitrage_order_legs
                        ADD COLUMN retry_count INT NOT NULL DEFAULT 0
                        AFTER requested_value_usdt
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
                  AND TABLE_NAME = 'arbitrage_order_legs'
                  AND COLUMN_NAME = 'last_retry_at'
                """,
                (mysql_config.database,),
            )
            has_arbitrage_order_last_retry_at = int(cursor.fetchone()[0]) > 0
            if not has_arbitrage_order_last_retry_at:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE arbitrage_order_legs
                        ADD COLUMN last_retry_at DATETIME NULL
                        AFTER acknowledged_at
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
                  AND COLUMN_NAME = 'maker_fee_rate'
                """,
                (mysql_config.database,),
            )
            has_exchange_accounts_maker_fee_rate = int(cursor.fetchone()[0]) > 0
            if not has_exchange_accounts_maker_fee_rate:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE exchange_accounts
                        ADD COLUMN maker_fee_rate DECIMAL(10,6) NOT NULL DEFAULT 0.050000
                        AFTER current_available_synced_at
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
                  AND COLUMN_NAME = 'taker_fee_rate'
                """,
                (mysql_config.database,),
            )
            has_exchange_accounts_taker_fee_rate = int(cursor.fetchone()[0]) > 0
            if not has_exchange_accounts_taker_fee_rate:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE exchange_accounts
                        ADD COLUMN taker_fee_rate DECIMAL(10,6) NOT NULL DEFAULT 0.050000
                        AFTER maker_fee_rate
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
                  AND COLUMN_NAME = 'fee_rate_synced_at'
                """,
                (mysql_config.database,),
            )
            has_exchange_accounts_fee_rate_synced_at = int(cursor.fetchone()[0]) > 0
            if not has_exchange_accounts_fee_rate_synced_at:
                try:
                    cursor.execute(
                        """
                        ALTER TABLE exchange_accounts
                        ADD COLUMN fee_rate_synced_at DATETIME NULL
                        AFTER taker_fee_rate
                        """
                    )
                except MySQLError as exc:
                    if "Duplicate column name" not in str(exc):
                        raise
            cursor.execute(
                """
                UPDATE strategy_rules
                SET max_position_usdt = order_amount_usdt
                WHERE max_position_usdt <= 0
                  AND order_amount_usdt > 0
                """
            )
            cursor.execute(
                """
                INSERT INTO system_exchange_configs (
                    exchange_code,
                    is_enabled,
                    use_public_api,
                    api_key,
                    api_secret,
                    api_passphrase,
                    remark
                )
                VALUES
                    ('binance', 1, 1, '', '', '', '默认公开接口'),
                    ('bitget', 1, 1, '', '', '', '默认公开接口'),
                    ('okx', 1, 1, '', '', '', '默认公开接口'),
                    ('gate', 1, 1, '', '', '', '默认公开接口'),
                    ('htx', 1, 1, '', '', '', '默认公开接口')
                ON DUPLICATE KEY UPDATE
                    exchange_code = VALUES(exchange_code)
                """
            )
            cursor.execute(
                """
                INSERT INTO system_runtime_configs (
                    config_key,
                    config_value,
                    remark
                )
                VALUES (
                    'asset_blacklist',
                    '',
                    '全局币种黑名单，命中后显示冻结且不参与开仓/加仓'
                )
                ON DUPLICATE KEY UPDATE
                    config_key = VALUES(config_key)
                """
            )
            connection.commit()
        finally:
            cursor.close()

    def _migrate_legacy_public_opportunity_snapshots(self, cursor) -> None:
        cursor.execute(
            """
            INSERT INTO public_opportunity_snapshots (
                channel,
                snapshot_json,
                row_count,
                generated_at,
                updated_at
            )
            SELECT
                SUBSTRING(channel, 8) AS channel,
                snapshot_json,
                row_count,
                generated_at,
                updated_at
            FROM opportunity_snapshots
            WHERE channel LIKE 'public:%'
            ORDER BY generated_at ASC, updated_at ASC, id ASC
            ON DUPLICATE KEY UPDATE
                snapshot_json = VALUES(snapshot_json),
                row_count = VALUES(row_count),
                generated_at = VALUES(generated_at),
                updated_at = VALUES(updated_at)
            """
        )

    def _ensure_column(
        self,
        cursor,
        *,
        table_name: str,
        column_name: str,
        ddl: str,
    ) -> None:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
            """,
            (mysql_config.database, table_name, column_name),
        )
        if int(cursor.fetchone()[0]) > 0:
            return
        try:
            cursor.execute(ddl)
        except MySQLError as exc:
            if "Duplicate column name" not in str(exc):
                raise

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
    def advisory_lock(
        self,
        connection: mysql.connector.MySQLConnection,
        lock_name: str,
        timeout_seconds: int = 30,
    ) -> Generator[None, None, None]:
        cursor = connection.cursor()
        acquired = False
        try:
            cursor.execute("SELECT GET_LOCK(%s, %s)", (lock_name, timeout_seconds))
            row = cursor.fetchone()
            acquired = bool(row and int(row[0] or 0) == 1)
            if not acquired:
                raise RuntimeError(f"Failed to acquire MySQL advisory lock: {lock_name}")
            yield
        finally:
            if acquired:
                try:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                    cursor.fetchone()
                except MySQLError:
                    logger.exception("Failed to release MySQL advisory lock: %s", lock_name)
            cursor.close()

    @contextmanager
    def connection(self) -> Generator[mysql.connector.MySQLConnection, None, None]:
        if self._pool is None or (not self._initialized and not self._initializing):
            self.initialize()

        assert self._pool is not None
        connection = self._pool.get_connection()
        try:
            yield connection
        finally:
            connection.close()


mysql_manager = MySQLConnectionManager()
