from __future__ import annotations

import mysql.connector

from app.config import mysql_config


def ensure_database() -> None:
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
