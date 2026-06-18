from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
import time
import logging
from pathlib import Path
from typing import Sequence

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

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
from app.controller.api_controller import router as api_router
from app.controller.page_controller import router as page_router
from app.infrastructure.cache import (
    account_balance_cache,
    market_runtime_cache,
    redis_runtime_support,
    redis_session_cache,
    strategy_runtime_cache,
)
from app.infrastructure.persistence import mysql_manager


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
logger = logging.getLogger(__name__)
SPAWN_WORKER_ON_STARTUP = False
WORKER_PROCESS: subprocess.Popen | None = None

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


def _spawn_worker_process() -> None:
    global WORKER_PROCESS
    if WORKER_PROCESS is not None and WORKER_PROCESS.poll() is None:
        return
    WORKER_PROCESS = subprocess.Popen(
        [sys.executable, "-m", "app.main", "worker"],
        cwd=str(PROJECT_ROOT),
    )
    logger.info("Worker process started: pid=%s", WORKER_PROCESS.pid)


def _stop_worker_process() -> None:
    global WORKER_PROCESS
    if WORKER_PROCESS is None:
        return
    if WORKER_PROCESS.poll() is None:
        WORKER_PROCESS.terminate()
        try:
            WORKER_PROCESS.wait(timeout=10)
        except subprocess.TimeoutExpired:
            WORKER_PROCESS.kill()
            WORKER_PROCESS.wait(timeout=5)
    logger.info("Worker process stopped.")
    WORKER_PROCESS = None


app = FastAPI(
    title="多交易所套利系统",
    description="多交易所套利系统。",
    version="0.1.0",
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "views" / "static")),
    name="static",
)

app.include_router(api_router)
app.include_router(page_router)


@app.on_event("startup")
async def startup_event() -> None:
    initialize_runtime_dependencies(include_session_cache=True)
    if SPAWN_WORKER_ON_STARTUP:
        _spawn_worker_process()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if SPAWN_WORKER_ON_STARTUP:
        _stop_worker_process()


def run_web(*, host: str, port: int, spawn_worker: bool = False) -> None:
    global SPAWN_WORKER_ON_STARTUP
    SPAWN_WORKER_ON_STARTUP = spawn_worker
    uvicorn.run(app, host=host, port=port)


def run_worker() -> None:
    initialize_runtime_dependencies(include_session_cache=False)
    start_background_workers()

    stop_event = threading.Event()

    def _handle_signal(signum, frame) -> None:  # type: ignore[unused-argument]
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not stop_event.is_set():
        time.sleep(1)


def run_all(*, host: str, port: int) -> None:
    run_web(host=host, port=port, spawn_worker=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified runtime entrypoint for web and worker processes.")
    subparsers = parser.add_subparsers(dest="mode")

    web_parser = subparsers.add_parser("web", help="Run the FastAPI web process.")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8000)

    subparsers.add_parser("worker", help="Run background worker threads only.")

    all_parser = subparsers.add_parser("all", help="Run the web process and spawn a worker process.")
    all_parser.add_argument("--host", default="127.0.0.1")
    all_parser.add_argument("--port", type=int, default=8000)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    mode = args.mode or "all"

    if mode == "worker":
        run_worker()
        return 0

    host = getattr(args, "host", "127.0.0.1")
    port = int(getattr(args, "port", 8000))

    if mode == "web":
        run_web(host=host, port=port)
        return 0

    if mode == "all":
        run_all(host=host, port=port)
        return 0

    parser.error(f"unsupported mode: {mode}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
