"""MySQL-backed repository for system exchange configs."""

from __future__ import annotations

from typing import Any, Dict, List

from app.domain.entities import SystemExchangeConfig, SystemRuntimeConfig
from app.infrastructure.persistence import mysql_manager


class MySQLSystemExchangeRepository:
    def list_configs(self) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    exchange_code,
                    is_enabled,
                    use_public_api,
                    api_key,
                    api_secret,
                    api_passphrase,
                    remark,
                    created_at,
                    updated_at
                FROM system_exchange_configs
                ORDER BY id ASC
                """
            )
            return list(cursor.fetchall())

    def get_config_by_exchange_code(self, exchange_code: str) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    exchange_code,
                    is_enabled,
                    use_public_api,
                    api_key,
                    api_secret,
                    api_passphrase,
                    remark,
                    created_at,
                    updated_at
                FROM system_exchange_configs
                WHERE exchange_code = %s
                LIMIT 1
                """,
                (exchange_code,),
            )
            return cursor.fetchone()

    def upsert_config(
        self,
        *,
        exchange_code: str,
        is_enabled: bool,
        use_public_api: bool,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        remark: str,
    ) -> SystemExchangeConfig:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
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
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    is_enabled = VALUES(is_enabled),
                    use_public_api = VALUES(use_public_api),
                    api_key = VALUES(api_key),
                    api_secret = VALUES(api_secret),
                    api_passphrase = VALUES(api_passphrase),
                    remark = VALUES(remark),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    exchange_code,
                    1 if is_enabled else 0,
                    1 if use_public_api else 0,
                    api_key,
                    api_secret,
                    api_passphrase,
                    remark,
                ),
            )
            connection.commit()

            cursor.execute(
                """
                SELECT
                    id,
                    exchange_code,
                    is_enabled,
                    use_public_api,
                    api_key,
                    api_secret,
                    api_passphrase,
                    remark,
                    created_at,
                    updated_at
                FROM system_exchange_configs
                WHERE exchange_code = %s
                LIMIT 1
                """,
                (exchange_code,),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._build_entity(row)

    def get_runtime_config(self, config_key: str) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id,
                    config_key,
                    config_value,
                    remark,
                    created_at,
                    updated_at
                FROM system_runtime_configs
                WHERE config_key = %s
                LIMIT 1
                """,
                (config_key,),
            )
            return cursor.fetchone()

    def upsert_runtime_config(
        self,
        *,
        config_key: str,
        config_value: str,
        remark: str,
    ) -> SystemRuntimeConfig:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                INSERT INTO system_runtime_configs (
                    config_key,
                    config_value,
                    remark
                )
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    config_value = VALUES(config_value),
                    remark = VALUES(remark),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    config_key,
                    config_value,
                    remark,
                ),
            )
            connection.commit()

            cursor.execute(
                """
                SELECT
                    id,
                    config_key,
                    config_value,
                    remark,
                    created_at,
                    updated_at
                FROM system_runtime_configs
                WHERE config_key = %s
                LIMIT 1
                """,
                (config_key,),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._build_runtime_entity(row)

    def _build_entity(self, row: Dict[str, Any]) -> SystemExchangeConfig:
        return SystemExchangeConfig(
            id=int(row["id"]),
            exchange_code=str(row["exchange_code"]),
            is_enabled=bool(row.get("is_enabled")),
            use_public_api=bool(row.get("use_public_api")),
            api_key=str(row.get("api_key") or ""),
            api_secret=str(row.get("api_secret") or ""),
            api_passphrase=str(row.get("api_passphrase") or ""),
            remark=str(row.get("remark") or ""),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_runtime_entity(self, row: Dict[str, Any]) -> SystemRuntimeConfig:
        return SystemRuntimeConfig(
            id=int(row["id"]),
            config_key=str(row.get("config_key") or ""),
            config_value=str(row.get("config_value") or ""),
            remark=str(row.get("remark") or ""),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


system_exchange_repository = MySQLSystemExchangeRepository()
