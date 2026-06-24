"""Transfer-record persistence mixin."""

from __future__ import annotations

from typing import Any, Dict, List

from app.domain.entities import TransferRecord
from app.infrastructure.persistence import mysql_manager


class AccountRepositoryTransfersMixin:
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
        execute_status: str = "pending_execute",
        result_status: str = "none",
        failure_type: str = "",
        failure_reason: str = "",
        config_fingerprint: str = "",
        is_worker_enabled: bool = False,
        execution_checkpoint: str = "",
        execution_reference: str = "",
        execution_payload: str = "",
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
                    execute_status,
                    result_status,
                    failure_type,
                    failure_reason,
                    config_fingerprint,
                    is_worker_enabled,
                    result,
                    execution_checkpoint,
                    execution_reference,
                    execution_payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    from_account_id,
                    to_account_id,
                    amount,
                    reason,
                    status,
                    execute_status,
                    result_status,
                    failure_type,
                    failure_reason,
                    config_fingerprint,
                    1 if is_worker_enabled else 0,
                    result,
                    execution_checkpoint,
                    execution_reference,
                    execution_payload or None,
                ),
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
                    execute_status,
                    result_status,
                    failure_type,
                    failure_reason,
                    config_fingerprint,
                    result,
                    execution_checkpoint,
                    execution_reference,
                    execution_payload,
                    processed_at,
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

    def list_pending_worker_transfer_records(self, limit: int = 20) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
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
                    execute_status,
                    result_status,
                    failure_type,
                    failure_reason,
                    config_fingerprint,
                    is_worker_enabled,
                    result,
                    execution_checkpoint,
                    execution_reference,
                    execution_payload,
                    processed_at,
                    created_at,
                    updated_at
                FROM account_transfer_records
                WHERE is_worker_enabled = 1
                  AND (
                    execute_status = 'pending_execute'
                    OR (execute_status = 'executing' AND result_status = 'none')
                  )
                ORDER BY id ASC
                LIMIT %s
                """,
                (limit,),
            )
            return list(cursor.fetchall())

    def get_open_worker_transfer_record_by_user_id(self, user_id: int) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
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
                    execute_status,
                    result_status,
                    failure_type,
                    failure_reason,
                    config_fingerprint,
                    is_worker_enabled,
                    result,
                    execution_checkpoint,
                    execution_reference,
                    execution_payload,
                    processed_at,
                    created_at,
                    updated_at
                FROM account_transfer_records
                WHERE user_id = %s
                  AND is_worker_enabled = 1
                  AND execute_status IN ('pending_execute', 'executing')
                ORDER BY id ASC
                LIMIT 1
                """,
                (user_id,),
            )
            return cursor.fetchone()

    def get_open_worker_transfer_record_by_target_account_id(self, to_account_id: int) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
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
                    execute_status,
                    result_status,
                    failure_type,
                    failure_reason,
                    config_fingerprint,
                    is_worker_enabled,
                    result,
                    execution_checkpoint,
                    execution_reference,
                    execution_payload,
                    processed_at,
                    created_at,
                    updated_at
                FROM account_transfer_records
                WHERE to_account_id = %s
                  AND is_worker_enabled = 1
                  AND execute_status IN ('pending_execute', 'executing')
                ORDER BY id ASC
                LIMIT 1
                """,
                (to_account_id,),
            )
            return cursor.fetchone()

    def get_open_worker_transfer_record_by_source_account_id(self, from_account_id: int) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
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
                    execute_status,
                    result_status,
                    failure_type,
                    failure_reason,
                    config_fingerprint,
                    is_worker_enabled,
                    result,
                    execution_checkpoint,
                    execution_reference,
                    execution_payload,
                    processed_at,
                    created_at,
                    updated_at
                FROM account_transfer_records
                WHERE from_account_id = %s
                  AND is_worker_enabled = 1
                  AND execute_status IN ('pending_execute', 'executing')
                ORDER BY id ASC
                LIMIT 1
                """,
                (from_account_id,),
            )
            return cursor.fetchone()

    def get_open_worker_transfer_record_by_route(
        self,
        *,
        user_id: int,
        from_account_id: int,
        to_account_id: int,
    ) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
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
                    execute_status,
                    result_status,
                    failure_type,
                    failure_reason,
                    config_fingerprint,
                    is_worker_enabled,
                    result,
                    execution_checkpoint,
                    execution_reference,
                    execution_payload,
                    processed_at,
                    created_at,
                    updated_at
                FROM account_transfer_records
                WHERE user_id = %s
                  AND from_account_id = %s
                  AND to_account_id = %s
                  AND is_worker_enabled = 1
                  AND execute_status IN ('pending_execute', 'executing')
                ORDER BY id ASC
                LIMIT 1
                """,
                (user_id, from_account_id, to_account_id),
            )
            return cursor.fetchone()

    def mark_transfer_record_processing(self, record_id: int, *, allow_recovering_executing: bool = False) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            execute_status_condition = (
                """
                  AND (
                    execute_status = 'pending_execute'
                    OR (execute_status = 'executing' AND result_status = 'none')
                  )
                """
                if allow_recovering_executing
                else """
                  AND execute_status = 'pending_execute'
                """
            )
            cursor.execute(
                f"""
                UPDATE account_transfer_records
                SET
                    status = 'processing',
                    execute_status = 'executing',
                    result_status = 'none',
                    result = CASE
                        WHEN execute_status = 'executing'
                             AND result_status = 'none'
                             AND COALESCE(NULLIF(result, ''), '') <> ''
                        THEN result
                        ELSE '后台线程已接单，开始执行调拨。'
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                  AND is_worker_enabled = 1
                  {execute_status_condition}
                """,
                (record_id,),
            )
            connection.commit()
            return cursor.rowcount > 0

    def update_transfer_record_status(
        self,
        record_id: int,
        *,
        status: str,
        result: str,
        execute_status: str = "processed",
        result_status: str = "none",
        failure_type: str = "",
        failure_reason: str = "",
        execution_checkpoint: str | None = None,
        execution_reference: str | None = None,
        execution_payload: str | None = None,
    ) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE account_transfer_records
                SET
                    status = %s,
                    execute_status = %s,
                    result_status = %s,
                    failure_type = %s,
                    failure_reason = %s,
                    result = %s,
                    execution_checkpoint = COALESCE(%s, execution_checkpoint),
                    execution_reference = COALESCE(%s, execution_reference),
                    execution_payload = COALESCE(%s, execution_payload),
                    processed_at = CASE
                        WHEN %s = 'processed' THEN CURRENT_TIMESTAMP
                        ELSE processed_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    status,
                    execute_status,
                    result_status,
                    failure_type,
                    failure_reason,
                    result,
                    execution_checkpoint,
                    execution_reference,
                    execution_payload,
                    execute_status,
                    record_id,
                ),
            )
            connection.commit()
            return cursor.rowcount > 0

    def update_transfer_record_execution_checkpoint(
        self,
        record_id: int,
        *,
        execution_checkpoint: str,
        execution_reference: str = "",
        execution_payload: str = "",
    ) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE account_transfer_records
                SET
                    execution_checkpoint = %s,
                    execution_reference = %s,
                    execution_payload = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    execution_checkpoint,
                    execution_reference,
                    execution_payload or None,
                    record_id,
                ),
            )
            connection.commit()
            return cursor.rowcount > 0

    def update_transfer_record_actual_destination(
        self,
        record_id: int,
        *,
        to_network: str,
        to_address_value: str,
        to_memo_tag: str,
    ) -> bool:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE account_transfer_records
                SET
                    actual_to_network = %s,
                    actual_to_address_value = %s,
                    actual_to_memo_tag = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    to_network,
                    to_address_value,
                    to_memo_tag,
                    record_id,
                ),
            )
            connection.commit()
            return cursor.rowcount > 0

    def get_transfer_record_execution_context(self, record_id: int) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    tr.id,
                    tr.user_id,
                    u.is_active AS user_is_active,
                    tr.from_account_id,
                    tr.to_account_id,
                    tr.amount,
                    tr.reason,
                    tr.status,
                    tr.execute_status,
                    tr.result_status,
                    tr.failure_type,
                    tr.failure_reason,
                    tr.config_fingerprint,
                    tr.is_worker_enabled,
                    tr.result,
                    tr.execution_checkpoint,
                    tr.execution_reference,
                    tr.execution_payload,
                    tr.processed_at,
                    tr.created_at,
                    tr.updated_at,
                    fa.id AS from_id,
                    fa.user_id AS from_user_id,
                    fa.market_type AS from_market_type,
                    fa.exchange_code AS from_exchange_code,
                    fa.account_name AS from_account_name,
                    fa.api_key AS from_api_key,
                    fa.api_secret AS from_api_secret,
                    fa.api_passphrase AS from_api_passphrase,
                    fa.connection_test_status AS from_connection_test_status,
                    fa.funding_ratio_percent AS from_funding_ratio_percent,
                    fa.current_available_amount AS from_current_available_amount,
                    fa.current_available_synced_at AS from_current_available_synced_at,
                    fa.is_active AS from_is_active,
                    fa.created_at AS from_created_at,
                    fa.updated_at AS from_updated_at,
                    faddr.network AS from_network,
                    faddr.address_value AS from_address_value,
                    faddr.memo_tag AS from_memo_tag,
                    ta.id AS to_id,
                    ta.user_id AS to_user_id,
                    ta.market_type AS to_market_type,
                    ta.exchange_code AS to_exchange_code,
                    ta.account_name AS to_account_name,
                    ta.api_key AS to_api_key,
                    ta.api_secret AS to_api_secret,
                    ta.api_passphrase AS to_api_passphrase,
                    ta.connection_test_status AS to_connection_test_status,
                    ta.funding_ratio_percent AS to_funding_ratio_percent,
                    ta.current_available_amount AS to_current_available_amount,
                    ta.current_available_synced_at AS to_current_available_synced_at,
                    ta.is_active AS to_is_active,
                    ta.created_at AS to_created_at,
                    ta.updated_at AS to_updated_at,
                    taddr.network AS to_network,
                    taddr.address_value AS to_address_value,
                    taddr.memo_tag AS to_memo_tag
                FROM account_transfer_records AS tr
                INNER JOIN users AS u
                    ON u.id = tr.user_id
                INNER JOIN exchange_accounts AS fa
                    ON fa.id = tr.from_account_id
                INNER JOIN exchange_accounts AS ta
                    ON ta.id = tr.to_account_id
                LEFT JOIN account_funding_addresses AS faddr
                    ON faddr.account_id = fa.id
                LEFT JOIN account_funding_addresses AS taddr
                    ON taddr.account_id = ta.id
                WHERE tr.id = %s
                LIMIT 1
                """,
                (record_id,),
            )
            return cursor.fetchone()

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
                    tr.execute_status,
                    tr.result_status,
                    tr.failure_type,
                    tr.failure_reason,
                    tr.config_fingerprint,
                    tr.result,
                    tr.execution_checkpoint,
                    tr.execution_reference,
                    tr.execution_payload,
                    tr.processed_at,
                    tr.created_at,
                    tr.updated_at,
                    fa.account_name AS from_account_name,
                    fa.exchange_code AS from_exchange_code,
                    ta.account_name AS to_account_name,
                    ta.exchange_code AS to_exchange_code,
                    COALESCE(NULLIF(tr.actual_to_network, ''), taddr.network) AS to_network,
                    COALESCE(NULLIF(tr.actual_to_address_value, ''), taddr.address_value) AS to_address_value,
                    COALESCE(NULLIF(tr.actual_to_memo_tag, ''), taddr.memo_tag) AS to_memo_tag
                FROM account_transfer_records AS tr
                INNER JOIN exchange_accounts AS fa
                    ON fa.id = tr.from_account_id
                INNER JOIN exchange_accounts AS ta
                    ON ta.id = tr.to_account_id
                LEFT JOIN account_funding_addresses AS taddr
                    ON taddr.account_id = ta.id
                WHERE tr.user_id = %s
                ORDER BY tr.id DESC
                """,
                (user_id,),
            )
            return list(cursor.fetchall())

    def list_open_worker_transfer_account_ids(self) -> List[int]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT DISTINCT account_id
                FROM (
                    SELECT from_account_id AS account_id
                    FROM account_transfer_records
                    WHERE is_worker_enabled = 1
                      AND execute_status IN ('pending_execute', 'executing')
                    UNION
                    SELECT to_account_id AS account_id
                    FROM account_transfer_records
                    WHERE is_worker_enabled = 1
                      AND execute_status IN ('pending_execute', 'executing')
                ) AS runtime_accounts
                WHERE account_id > 0
                ORDER BY account_id ASC
                """
            )
            return [int(row["account_id"]) for row in cursor.fetchall()]
