"""Auto-transfer, strategy-rule, and account-list persistence mixin."""

from __future__ import annotations

from typing import Any, Dict, List

from app.domain.entities import AutoTransferConfig, StrategyRule
from app.infrastructure.persistence import mysql_manager


class AccountRepositoryAutomationMixin:
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

    def list_enabled_auto_transfer_user_ids(self) -> List[int]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT DISTINCT cfg.user_id
                FROM account_auto_transfer_configs AS cfg
                INNER JOIN users AS u
                    ON u.id = cfg.user_id
                INNER JOIN exchange_accounts AS a
                    ON a.user_id = cfg.user_id
                WHERE cfg.is_enabled = 1
                  AND u.is_active = 1
                  AND a.is_active = 1
                ORDER BY cfg.user_id ASC
                """
            )
            return [int(row["user_id"]) for row in cursor.fetchall()]

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
                    min_net_funding_rate_threshold,
                    spread_rate_threshold,
                    min_close_spread_rate_threshold,
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

    def list_active_user_ids_with_accounts(self) -> List[int]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT DISTINCT a.user_id
                FROM exchange_accounts AS a
                INNER JOIN users AS u
                    ON u.id = a.user_id
                WHERE a.is_active = 1
                  AND u.is_active = 1
                ORDER BY a.user_id ASC
                """
            )
            return [int(row["user_id"]) for row in cursor.fetchall()]

    def get_active_account_counts_by_user_id(self) -> Dict[int, int]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT a.user_id, COUNT(*) AS account_count
                FROM exchange_accounts AS a
                INNER JOIN users AS u
                    ON u.id = a.user_id
                WHERE a.is_active = 1
                  AND u.is_active = 1
                GROUP BY a.user_id
                """
            )
            return {
                int(row["user_id"]): int(row.get("account_count") or 0)
                for row in cursor.fetchall()
            }

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
                    min_net_funding_rate_threshold,
                    spread_rate_threshold,
                    min_close_spread_rate_threshold,
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
        min_net_funding_rate_threshold: float,
        spread_rate_threshold: float,
        min_close_spread_rate_threshold: float,
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
                    min_net_funding_rate_threshold,
                    spread_rate_threshold,
                    min_close_spread_rate_threshold,
                    max_spread_rate_threshold,
                    max_pairs,
                    order_amount_usdt,
                    max_position_usdt,
                    order_interval_seconds,
                    is_enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    name,
                    strategy_type,
                    annualized_rate_threshold,
                    min_net_funding_rate_threshold,
                    spread_rate_threshold,
                    min_close_spread_rate_threshold,
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
                    min_net_funding_rate_threshold,
                    spread_rate_threshold,
                    min_close_spread_rate_threshold,
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
        min_net_funding_rate_threshold: float,
        spread_rate_threshold: float,
        min_close_spread_rate_threshold: float,
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
                    min_net_funding_rate_threshold = %s,
                    spread_rate_threshold = %s,
                    min_close_spread_rate_threshold = %s,
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
                    min_net_funding_rate_threshold,
                    spread_rate_threshold,
                    min_close_spread_rate_threshold,
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
                    min_net_funding_rate_threshold,
                    spread_rate_threshold,
                    min_close_spread_rate_threshold,
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
                WHERE a.user_id = %s
                ORDER BY a.id DESC
                """,
                (user_id,),
            )
            return list(cursor.fetchall())

    def list_active_accounts_with_address_by_user_id(self, user_id: int) -> List[Dict[str, Any]]:
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
                WHERE a.user_id = %s
                  AND a.is_active = 1
                  AND u.is_active = 1
                ORDER BY a.id DESC
                """,
                (user_id,),
            )
            return list(cursor.fetchall())

    def list_accounts_with_address_by_ids(self, account_ids: List[int]) -> List[Dict[str, Any]]:
        normalized_ids = sorted({int(account_id) for account_id in account_ids if int(account_id) > 0})
        if not normalized_ids:
            return []

        placeholders = ", ".join(["%s"] * len(normalized_ids))
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"""
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
                WHERE a.id IN ({placeholders})
                ORDER BY a.id DESC
                """,
                tuple(normalized_ids),
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
                WHERE a.is_active = 1
                  AND u.is_active = 1
                ORDER BY a.id DESC
                """
            )
            return list(cursor.fetchall())
