from __future__ import annotations

import logging
import signal
import subprocess
import sys
import threading
import time

import uvicorn
from fastapi import FastAPI

from app.bootstrap import initialize_runtime_dependencies, start_background_workers
from app.core.paths import PROJECT_ROOT


logger = logging.getLogger(__name__)

_spawn_worker_on_startup = False
_worker_process: subprocess.Popen | None = None


def should_spawn_worker_on_startup() -> bool:
    return _spawn_worker_on_startup


def set_spawn_worker_on_startup(value: bool) -> None:
    global _spawn_worker_on_startup
    _spawn_worker_on_startup = value


def spawn_worker_process() -> None:
    global _worker_process
    if _worker_process is not None and _worker_process.poll() is None:
        return
    _worker_process = subprocess.Popen(
        [sys.executable, "-m", "app.main", "worker"],
        cwd=str(PROJECT_ROOT),
    )
    logger.info("Worker process started: pid=%s", _worker_process.pid)


def stop_worker_process() -> None:
    global _worker_process
    if _worker_process is None:
        return
    if _worker_process.poll() is None:
        _worker_process.terminate()
        try:
            _worker_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _worker_process.kill()
            _worker_process.wait(timeout=5)
    logger.info("Worker process stopped.")
    _worker_process = None


def run_web(app: FastAPI, *, host: str, port: int, spawn_worker: bool = False) -> None:
    set_spawn_worker_on_startup(spawn_worker)
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


def run_all(app: FastAPI, *, host: str, port: int) -> None:
    run_web(app, host=host, port=port, spawn_worker=True)
