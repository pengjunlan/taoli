"""MySQL configuration for persistence and audit data."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MySQLConfig:
    host: str = os.getenv("ARBI_MYSQL_HOST", "127.0.0.1")
    port: int = int(os.getenv("ARBI_MYSQL_PORT", "3306"))
    user: str = os.getenv("ARBI_MYSQL_USER", "root")
    password: str = os.getenv("ARBI_MYSQL_PASSWORD", "")
    database: str = os.getenv("ARBI_MYSQL_DATABASE", "arbitrage_system")
    charset: str = os.getenv("ARBI_MYSQL_CHARSET", "utf8mb4")
    pool_name: str = os.getenv("ARBI_MYSQL_POOL_NAME", "arbitrage_system_pool")
    pool_size: int = int(os.getenv("ARBI_MYSQL_POOL_SIZE", "10"))
    connection_timeout: int = int(os.getenv("ARBI_MYSQL_CONNECTION_TIMEOUT", "5"))


mysql_config = MySQLConfig()
