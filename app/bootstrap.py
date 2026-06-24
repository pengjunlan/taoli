from __future__ import annotations

import logging

from app.application.services.account_monitor_service import account_monitor_service
from app.application.services.arbitrage_execution_monitor_service import arbitrage_execution_monitor_service
from app.application.services.arbitrage_opportunity_monitor_service import arbitrage_opportunity_monitor_service
from app.application.services.arbitrage_position_monitor_service import arbitrage_position_monitor_service
from app.application.services.auto_transfer_monitor_service import auto_transfer_monitor_service
from app.application.services.log_cleanup_service import (
    cleanup_expired_logs,
    cleanup_legacy_runtime_cache_dir,
    organize_legacy_root_logs,
)
from app.application.services.market_data_monitor_service import market_data_monitor_service
from app.application.services.opportunity_runtime_service import opportunity_runtime_service
from app.application.services.transfer_execution_monitor_service import transfer_execution_monitor_service
from app.config.logging import setup_logging
from app.infrastructure.cache import (
    account_balance_cache,
    market_runtime_cache,
    redis_runtime_support,
    redis_session_cache,
    strategy_runtime_cache,
)
from app.infrastructure.persistence import mysql_manager


logger = logging.getLogger(__name__)


def initialize_process_environment() -> None:
    setup_logging()
    organize_legacy_root_logs()
    cleanup_expired_logs()
    cleanup_legacy_runtime_cache_dir()


def initialize_runtime_dependencies(*, include_session_cache: bool = True) -> None:
    logger.info("Runtime init start: mysql")
    mysql_manager.initialize()
    logger.info("Runtime init done: mysql")
    if include_session_cache:
        logger.info("Runtime init start: redis_session_cache")
        redis_session_cache.initialize()
        logger.info("Runtime init done: redis_session_cache")
    logger.info("Runtime init start: redis_runtime_support")
    redis_runtime_support.initialize()
    logger.info("Runtime init done: redis_runtime_support")
    logger.info("Runtime init start: account_balance_cache")
    account_balance_cache.initialize()
    logger.info("Runtime init done: account_balance_cache")
    logger.info("Runtime init start: market_runtime_cache")
    market_runtime_cache.initialize()
    logger.info("Runtime init done: market_runtime_cache")
    logger.info("Runtime init start: strategy_runtime_cache")
    strategy_runtime_cache.initialize()
    logger.info("Runtime init done: strategy_runtime_cache")


def start_background_workers() -> None:
    account_monitor_service.start()
    market_data_monitor_service.start()
    auto_transfer_monitor_service.start()
    transfer_execution_monitor_service.start()
    opportunity_runtime_service.start()
    arbitrage_opportunity_monitor_service.start()
    arbitrage_execution_monitor_service.start()
    arbitrage_position_monitor_service.start()
