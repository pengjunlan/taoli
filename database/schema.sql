-- Local schema backup generated on 2026-06-12
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS=0;

DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `username` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password_hash` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `is_admin` tinyint(1) NOT NULL DEFAULT '0',
  `last_login_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=23 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `user_sessions`;
CREATE TABLE `user_sessions` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `session_token_hash` char(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `expires_at` datetime NOT NULL,
  `is_revoked` tinyint(1) NOT NULL DEFAULT '0',
  `ip_address` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_agent` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `last_seen_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sessions_token_hash` (`session_token_hash`),
  KEY `idx_sessions_user_id` (`user_id`),
  KEY `idx_sessions_expires_at` (`expires_at`),
  CONSTRAINT `fk_user_sessions_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=40 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `auth_login_logs`;
CREATE TABLE `auth_login_logs` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned DEFAULT NULL,
  `username` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_success` tinyint(1) NOT NULL,
  `failure_reason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `ip_address` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_agent` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_auth_login_logs_user_id` (`user_id`),
  KEY `idx_auth_login_logs_created_at` (`created_at`),
  CONSTRAINT `fk_auth_login_logs_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=46 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `exchange_accounts`;
CREATE TABLE `exchange_accounts` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `market_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `account_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `api_key` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `api_secret` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `api_passphrase` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `connection_test_status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'untested',
  `funding_ratio_percent` decimal(10,2) NOT NULL DEFAULT '0.00',
  `current_available_amount` decimal(18,8) NOT NULL DEFAULT '0.00000000',
  `current_available_synced_at` datetime DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_exchange_accounts_user_id` (`user_id`),
  KEY `idx_exchange_accounts_exchange_code` (`exchange_code`),
  CONSTRAINT `fk_exchange_accounts_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=26 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `account_funding_addresses`;
CREATE TABLE `account_funding_addresses` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `account_id` bigint unsigned NOT NULL,
  `network` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `address_value` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `memo_tag` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_account_funding_addresses_account_id` (`account_id`),
  CONSTRAINT `fk_account_funding_addresses_account` FOREIGN KEY (`account_id`) REFERENCES `exchange_accounts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=43 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `account_transfer_records`;
CREATE TABLE `account_transfer_records` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `from_account_id` bigint unsigned NOT NULL,
  `to_account_id` bigint unsigned NOT NULL,
  `amount` decimal(18,2) NOT NULL DEFAULT '0.00',
  `reason` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '手动调拨',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'created',
  `is_worker_enabled` tinyint(1) NOT NULL DEFAULT '0',
  `result` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '手动调拨已登记，等待后续执行。',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_account_transfer_records_user_id` (`user_id`),
  KEY `idx_account_transfer_records_from_account_id` (`from_account_id`),
  KEY `idx_account_transfer_records_to_account_id` (`to_account_id`),
  KEY `idx_account_transfer_records_worker_status` (`is_worker_enabled`,`status`),
  CONSTRAINT `fk_account_transfer_records_from_account` FOREIGN KEY (`from_account_id`) REFERENCES `exchange_accounts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_account_transfer_records_to_account` FOREIGN KEY (`to_account_id`) REFERENCES `exchange_accounts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_account_transfer_records_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `account_auto_transfer_configs`;
CREATE TABLE `account_auto_transfer_configs` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `is_enabled` tinyint(1) NOT NULL DEFAULT '0',
  `trigger_ratio` decimal(10,4) NOT NULL DEFAULT '0.5000',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_account_auto_transfer_configs_user_id` (`user_id`),
  CONSTRAINT `fk_account_auto_transfer_configs_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=26 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `strategy_rules`;
CREATE TABLE `strategy_rules` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `strategy_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `annualized_rate_threshold` decimal(10,4) NOT NULL DEFAULT '0.0000',
  `spread_rate_threshold` decimal(10,4) NOT NULL DEFAULT '0.0000',
  `max_spread_rate_threshold` decimal(10,4) NOT NULL DEFAULT '0.0000',
  `exchanges_scope` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `max_pairs` int NOT NULL DEFAULT '1',
  `order_amount_usdt` decimal(18,2) NOT NULL DEFAULT '0.00',
  `max_position_usdt` decimal(18,2) NOT NULL DEFAULT '0.00',
  `order_interval_seconds` int NOT NULL DEFAULT '0',
  `is_enabled` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_strategy_rules_user_id` (`user_id`),
  KEY `idx_strategy_rules_type` (`strategy_type`),
  CONSTRAINT `fk_strategy_rules_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `exchange_markets`;
CREATE TABLE `exchange_markets` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `market_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `symbol` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `symbol_normalized` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `base_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `quote_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `settle_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `is_contract` tinyint(1) NOT NULL DEFAULT '0',
  `is_linear` tinyint(1) NOT NULL DEFAULT '0',
  `contract_size` decimal(18,8) NOT NULL DEFAULT '0.00000000',
  `price_precision` decimal(18,8) NOT NULL DEFAULT '0.00000000',
  `amount_precision` decimal(18,8) NOT NULL DEFAULT '0.00000000',
  `min_amount` decimal(18,8) NOT NULL DEFAULT '0.00000000',
  `supports_funding` tinyint(1) NOT NULL DEFAULT '0',
  `supports_ws` tinyint(1) NOT NULL DEFAULT '1',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `synced_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exchange_markets_unique` (`exchange_code`,`market_type`,`symbol`),
  KEY `idx_exchange_markets_symbol_normalized` (`symbol_normalized`),
  KEY `idx_exchange_markets_exchange_market` (`exchange_code`,`market_type`)
) ENGINE=InnoDB AUTO_INCREMENT=32985 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `exchange_market_pairs`;
CREATE TABLE `exchange_market_pairs` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `pair_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `pair_key` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `left_exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `right_exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `left_market_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `right_market_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `symbol_normalized` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `left_symbol` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `right_symbol` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `base_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `quote_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `settle_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_mode` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'auto',
  `pair_reason` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `generated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exchange_market_pairs_pair_key` (`pair_key`),
  KEY `idx_exchange_market_pairs_type` (`pair_type`),
  KEY `idx_exchange_market_pairs_symbol` (`symbol_normalized`)
) ENGINE=InnoDB AUTO_INCREMENT=23791 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `arbitrage_executions`;
CREATE TABLE `arbitrage_executions` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `strategy_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `strategy_rule_id` bigint unsigned DEFAULT NULL,
  `strategy_rule_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `symbol` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `base_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `quote_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'USDT',
  `left_exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `right_exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `left_market_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `right_market_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `left_symbol` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `right_symbol` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `planned_order_amount_usdt` decimal(18,2) NOT NULL DEFAULT '0.00',
  `max_position_usdt` decimal(18,2) NOT NULL DEFAULT '0.00',
  `trigger_metric_primary` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `trigger_metric_secondary` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `trigger_metric_risk` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `trigger_reason` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'created',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_arbitrage_executions_user_status` (`user_id`,`status`),
  KEY `idx_arbitrage_executions_strategy_type` (`strategy_type`),
  KEY `idx_arbitrage_executions_symbol` (`symbol`),
  CONSTRAINT `fk_arbitrage_executions_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `arbitrage_order_legs`;
CREATE TABLE `arbitrage_order_legs` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `execution_id` bigint unsigned NOT NULL,
  `user_id` bigint unsigned NOT NULL,
  `exchange_account_id` bigint unsigned DEFAULT NULL,
  `leg_role` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'unknown',
  `position_side` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'net',
  `exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `market_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `symbol` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `side` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `order_type` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'market',
  `client_order_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `exchange_order_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `requested_price` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `requested_quantity` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `requested_value_usdt` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `average_fill_price` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `filled_quantity` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `filled_value_usdt` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'created',
  `status_message` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `submitted_at` datetime DEFAULT NULL,
  `acknowledged_at` datetime DEFAULT NULL,
  `closed_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_arbitrage_order_legs_execution_id` (`execution_id`),
  KEY `idx_arbitrage_order_legs_user_status` (`user_id`,`status`),
  KEY `idx_arbitrage_order_legs_exchange_order_id` (`exchange_order_id`),
  KEY `fk_arbitrage_order_legs_account` (`exchange_account_id`),
  CONSTRAINT `fk_arbitrage_order_legs_account` FOREIGN KEY (`exchange_account_id`) REFERENCES `exchange_accounts` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_arbitrage_order_legs_execution` FOREIGN KEY (`execution_id`) REFERENCES `arbitrage_executions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_arbitrage_order_legs_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `arbitrage_fill_records`;
CREATE TABLE `arbitrage_fill_records` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `execution_id` bigint unsigned NOT NULL,
  `order_leg_id` bigint unsigned NOT NULL,
  `user_id` bigint unsigned NOT NULL,
  `exchange_account_id` bigint unsigned DEFAULT NULL,
  `exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `market_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `symbol` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `position_side` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'net',
  `side` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `exchange_fill_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `fill_price` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `fill_quantity` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `fill_value_usdt` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `fee_amount` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `fee_asset` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `liquidity` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `filled_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_arbitrage_fill_records_execution_id` (`execution_id`),
  KEY `idx_arbitrage_fill_records_order_leg_id` (`order_leg_id`),
  KEY `idx_arbitrage_fill_records_user_id` (`user_id`),
  KEY `idx_arbitrage_fill_records_symbol` (`symbol`),
  KEY `fk_arbitrage_fill_records_account` (`exchange_account_id`),
  CONSTRAINT `fk_arbitrage_fill_records_account` FOREIGN KEY (`exchange_account_id`) REFERENCES `exchange_accounts` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_arbitrage_fill_records_execution` FOREIGN KEY (`execution_id`) REFERENCES `arbitrage_executions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_arbitrage_fill_records_order_leg` FOREIGN KEY (`order_leg_id`) REFERENCES `arbitrage_order_legs` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_arbitrage_fill_records_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `arbitrage_positions`;
CREATE TABLE `arbitrage_positions` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `exchange_account_id` bigint unsigned DEFAULT NULL,
  `exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `market_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `symbol` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `base_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `quote_asset` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'USDT',
  `position_side` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'net',
  `quantity` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `avg_entry_price` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `mark_price` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `market_value_usdt` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `realized_pnl_usdt` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `unrealized_pnl_usdt` decimal(28,12) NOT NULL DEFAULT '0.000000000000',
  `opened_by_execution_id` bigint unsigned DEFAULT NULL,
  `last_order_leg_id` bigint unsigned DEFAULT NULL,
  `last_fill_id` bigint unsigned DEFAULT NULL,
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'open',
  `last_synced_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_arbitrage_positions_account_symbol_side` (`exchange_account_id`,`market_type`,`symbol`,`position_side`),
  KEY `idx_arbitrage_positions_user_status` (`user_id`,`status`),
  KEY `idx_arbitrage_positions_symbol` (`symbol`),
  KEY `fk_arbitrage_positions_execution` (`opened_by_execution_id`),
  KEY `fk_arbitrage_positions_order_leg` (`last_order_leg_id`),
  KEY `fk_arbitrage_positions_fill` (`last_fill_id`),
  CONSTRAINT `fk_arbitrage_positions_account` FOREIGN KEY (`exchange_account_id`) REFERENCES `exchange_accounts` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_arbitrage_positions_execution` FOREIGN KEY (`opened_by_execution_id`) REFERENCES `arbitrage_executions` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_arbitrage_positions_fill` FOREIGN KEY (`last_fill_id`) REFERENCES `arbitrage_fill_records` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_arbitrage_positions_order_leg` FOREIGN KEY (`last_order_leg_id`) REFERENCES `arbitrage_order_legs` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_arbitrage_positions_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `opportunity_snapshots`;
CREATE TABLE `opportunity_snapshots` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `channel` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `snapshot_json` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `row_count` int NOT NULL DEFAULT '0',
  `generated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_opportunity_snapshots_user_channel` (`user_id`,`channel`),
  KEY `idx_opportunity_snapshots_channel` (`channel`),
  CONSTRAINT `fk_opportunity_snapshots_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=55 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `system_exchange_configs`;
CREATE TABLE `system_exchange_configs` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `exchange_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_enabled` tinyint(1) NOT NULL DEFAULT '1',
  `use_public_api` tinyint(1) NOT NULL DEFAULT '1',
  `api_key` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `api_secret` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `api_passphrase` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `remark` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_system_exchange_configs_exchange_code` (`exchange_code`)
) ENGINE=InnoDB AUTO_INCREMENT=321 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS=1;
