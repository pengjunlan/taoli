"""Persistence for user opportunity snapshots used during cold start."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from app.infrastructure.persistence import mysql_manager


class MySQLOpportunitySnapshotRepository:
    def upsert_snapshot(
        self,
        *,
        user_id: int,
        channel: str,
        payload: Dict[str, Any],
        row_count: int,
        generated_at: datetime | None,
    ) -> None:
        snapshot_json = json.dumps(payload, ensure_ascii=False, default=self._json_default)
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO opportunity_snapshots (
                    user_id,
                    channel,
                    snapshot_json,
                    row_count,
                    generated_at
                )
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    snapshot_json = VALUES(snapshot_json),
                    row_count = VALUES(row_count),
                    generated_at = VALUES(generated_at),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, channel, snapshot_json, row_count, generated_at or datetime.now()),
            )
            connection.commit()

    def get_snapshot(self, *, user_id: int, channel: str) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    user_id,
                    channel,
                    snapshot_json,
                    row_count,
                    generated_at,
                    updated_at
                FROM opportunity_snapshots
                WHERE user_id = %s
                  AND channel = %s
                LIMIT 1
                """,
                (user_id, channel),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            payload = self._loads_snapshot_json(str(row.get("snapshot_json") or ""))
            return {
                "user_id": int(row["user_id"]),
                "channel": str(row["channel"]),
                "payload": payload,
                "row_count": int(row.get("row_count") or 0),
                "generated_at": row.get("generated_at"),
                "updated_at": row.get("updated_at"),
            }

    def upsert_public_snapshot(
        self,
        *,
        channel: str,
        payload: Dict[str, Any],
        row_count: int,
        generated_at: datetime | None,
    ) -> None:
        snapshot_json = json.dumps(payload, ensure_ascii=False, default=self._json_default)
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO public_opportunity_snapshots (
                    channel,
                    snapshot_json,
                    row_count,
                    generated_at
                )
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    snapshot_json = VALUES(snapshot_json),
                    row_count = VALUES(row_count),
                    generated_at = VALUES(generated_at),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (channel, snapshot_json, row_count, generated_at or datetime.now()),
            )
            connection.commit()

    def get_public_snapshot(self, *, channel: str) -> Dict[str, Any] | None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    channel,
                    snapshot_json,
                    row_count,
                    generated_at,
                    updated_at
                FROM public_opportunity_snapshots
                WHERE channel = %s
                LIMIT 1
                """,
                (channel,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            payload = self._loads_snapshot_json(str(row.get("snapshot_json") or ""))
            return {
                "channel": str(row["channel"]),
                "payload": payload,
                "row_count": int(row.get("row_count") or 0),
                "generated_at": row.get("generated_at"),
                "updated_at": row.get("updated_at"),
            }

    def list_snapshot_counts(self) -> List[Dict[str, Any]]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    channel,
                    snapshot_count,
                    total_rows,
                    latest_generated_at
                FROM (
                    SELECT
                        channel,
                        COUNT(*) AS snapshot_count,
                        SUM(row_count) AS total_rows,
                        MAX(generated_at) AS latest_generated_at
                    FROM opportunity_snapshots
                    WHERE channel NOT LIKE 'public:%'
                    GROUP BY channel
                    UNION ALL
                    SELECT
                        CONCAT('public:', channel) AS channel,
                        COUNT(*) AS snapshot_count,
                        SUM(row_count) AS total_rows,
                        MAX(generated_at) AS latest_generated_at
                    FROM public_opportunity_snapshots
                    GROUP BY channel
                ) AS merged_snapshots
                ORDER BY channel ASC
                """
            )
            return list(cursor.fetchall())

    def _loads_snapshot_json(self, raw: str) -> Dict[str, Any]:
        text = raw.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _json_default(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)


opportunity_snapshot_repository = MySQLOpportunitySnapshotRepository()
