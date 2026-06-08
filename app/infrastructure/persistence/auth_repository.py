"""MySQL-backed auth repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import mysql.connector

from app.domain.entities import AuthSession, AuthUser
from app.infrastructure.persistence import mysql_manager


class MySQLAuthRepository:
    """Handles user, session and auth log persistence."""

    def create_user(self, username: str, password_hash: str) -> AuthUser:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    INSERT INTO users (username, password_hash)
                    VALUES (%s, %s)
                    """,
                    (username, password_hash),
                )
                connection.commit()
            except mysql.connector.IntegrityError:
                connection.rollback()
                raise

            cursor.execute(
                """
                SELECT id, username, password_hash, is_active, created_at, updated_at, last_login_at
                FROM users
                WHERE id = %s
                """,
                (cursor.lastrowid,),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._build_user(row)

    def get_user_by_username(self, username: str) -> Optional[AuthUser]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, username, password_hash, is_active, created_at, updated_at, last_login_at
                FROM users
                WHERE username = %s
                LIMIT 1
                """,
                (username,),
            )
            row = cursor.fetchone()
            return self._build_user(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[AuthUser]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, username, password_hash, is_active, created_at, updated_at, last_login_at
                FROM users
                WHERE id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            return self._build_user(row) if row else None

    def update_last_login(self, user_id: int) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE users
                SET last_login_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (user_id,),
            )
            connection.commit()

    def create_session(
        self,
        user_id: int,
        session_token_hash: str,
        expires_at: datetime,
        ip_address: str,
        user_agent: str,
    ) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO user_sessions (
                    user_id,
                    session_token_hash,
                    expires_at,
                    ip_address,
                    user_agent
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, session_token_hash, expires_at, ip_address, user_agent),
            )
            connection.commit()

    def get_active_session(self, session_token_hash: str) -> Optional[AuthSession]:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    s.session_token_hash,
                    s.expires_at,
                    s.created_at,
                    u.id,
                    u.username,
                    u.password_hash,
                    u.is_active,
                    u.created_at AS user_created_at,
                    u.updated_at AS user_updated_at,
                    u.last_login_at
                FROM user_sessions AS s
                INNER JOIN users AS u ON u.id = s.user_id
                WHERE s.session_token_hash = %s
                  AND s.is_revoked = 0
                  AND s.expires_at > UTC_TIMESTAMP()
                LIMIT 1
                """,
                (session_token_hash,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._build_session(row)

    def revoke_session(self, session_token_hash: str) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE user_sessions
                SET is_revoked = 1
                WHERE session_token_hash = %s
                """,
                (session_token_hash,),
            )
            connection.commit()

    def touch_session(self, session_token_hash: str) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE user_sessions
                SET last_seen_at = CURRENT_TIMESTAMP
                WHERE session_token_hash = %s
                """,
                (session_token_hash,),
            )
            connection.commit()

    def write_login_log(
        self,
        username: str,
        is_success: bool,
        ip_address: str,
        user_agent: str,
        user_id: Optional[int] = None,
        failure_reason: Optional[str] = None,
    ) -> None:
        with mysql_manager.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO auth_login_logs (
                    user_id,
                    username,
                    is_success,
                    failure_reason,
                    ip_address,
                    user_agent
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (user_id, username, int(is_success), failure_reason, ip_address, user_agent),
            )
            connection.commit()

    def _build_user(self, row: Dict[str, Any]) -> AuthUser:
        return AuthUser(
            id=int(row["id"]),
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row.get("last_login_at"),
        )

    def _build_session(self, row: Dict[str, Any]) -> AuthSession:
        user = AuthUser(
            id=int(row["id"]),
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            is_active=bool(row["is_active"]),
            created_at=row["user_created_at"],
            updated_at=row["user_updated_at"],
            last_login_at=row.get("last_login_at"),
        )
        return AuthSession(
            user=user,
            session_token_hash=str(row["session_token_hash"]),
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )


auth_repository = MySQLAuthRepository()
