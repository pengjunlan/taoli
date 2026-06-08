"""Application configuration package."""

from pathlib import Path

from app.config.env import load_env_file

load_env_file(Path(__file__).resolve().parents[2] / ".env")

from app.config.mysql import MySQLConfig, mysql_config
from app.config.redis import RedisConfig, redis_config
from app.config.settings import AppSettings, AuthSettings, settings

__all__ = [
    "AppSettings",
    "AuthSettings",
    "MySQLConfig",
    "RedisConfig",
    "load_env_file",
    "mysql_config",
    "redis_config",
    "settings",
]
