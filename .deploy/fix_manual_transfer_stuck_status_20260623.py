from __future__ import annotations

from app.infrastructure.persistence import mysql_manager


def main() -> None:
    mysql_manager.initialize()
    with mysql_manager.connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE account_transfer_records
            SET
                status = 'success',
                execute_status = 'processed',
                result_status = 'success',
                failure_type = '',
                failure_reason = '',
                result = CASE
                    WHEN COALESCE(NULLIF(execution_reference, ''), '') <> ''
                    THEN CONCAT('跨交易所调拨已完成，出金记录号 ', execution_reference, '。')
                    ELSE '跨交易所调拨已完成。'
                END,
                processed_at = COALESCE(processed_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE is_worker_enabled = 1
              AND result_status = 'none'
              AND execution_checkpoint IN ('same_exchange_completed', 'target_internal_transferred')
            """
        )
        repaired = int(cursor.rowcount or 0)
        connection.commit()
        print(f"REPAIRED {repaired}")


if __name__ == "__main__":
    main()
