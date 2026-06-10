"""Central logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.paths import LOG_DIR, RUNTIME_LOG_DIR, WORKER_LOG_DIR


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_LOG_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if any(getattr(handler, "_arbi_logging_handler", False) for handler in root_logger.handlers):
        return

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler._arbi_logging_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(console_handler)

    app_handler = _build_rotating_handler(LOG_DIR / "app.log", formatter)
    error_handler = _build_rotating_handler(LOG_DIR / "error.log", formatter, level=logging.WARNING)
    root_logger.addHandler(app_handler)
    root_logger.addHandler(error_handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)


def build_worker_logger(worker_key: str) -> logging.Logger:
    setup_logging()

    safe_name = worker_key.strip().lower().replace(" ", "_")
    logger_name = f"worker.{safe_name}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = True

    target_file = WORKER_LOG_DIR / f"{safe_name}.log"
    target_path = str(target_file.resolve())

    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", "") == target_path:
            return logger

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    handler = _build_rotating_handler(target_file, formatter)
    logger.addHandler(handler)
    return logger


def _build_rotating_handler(path: Path, formatter: logging.Formatter, *, level: int = logging.INFO) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        filename=str(path),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler._arbi_logging_handler = True  # type: ignore[attr-defined]
    return handler
