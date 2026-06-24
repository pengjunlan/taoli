from __future__ import annotations

from mysql.connector.pooling import MySQLConnectionPool

from app.config import mysql_config


def create_pool() -> MySQLConnectionPool:
    return MySQLConnectionPool(
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
