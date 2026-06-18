"""Helpers for organizing runtime log files."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.core.paths import APP_DIR, PROJECT_ROOT, RUNTIME_LOG_DIR


LOG_RETENTION_DAYS = 15


def organize_legacy_root_logs() -> None:
    archive_dir = RUNTIME_LOG_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    legacy_log_dir = PROJECT_ROOT / "log"
    if legacy_log_dir.exists() and legacy_log_dir != APP_DIR / "log":
        for path in legacy_log_dir.iterdir():
            target = (APP_DIR / "log") / path.name
            try:
                if target.exists():
                    if target.is_file():
                        target.unlink()
                path.replace(target)
            except Exception:
                continue
        try:
            legacy_log_dir.rmdir()
        except Exception:
            pass

    for path in PROJECT_ROOT.glob("*.log"):
        if path.parent != PROJECT_ROOT:
            continue
        target = archive_dir / path.name
        try:
            if target.exists():
                target.unlink()
            path.replace(target)
        except Exception:
            continue


def cleanup_expired_logs(*, retention_days: int = LOG_RETENTION_DAYS) -> None:
    cutoff = datetime.now() - timedelta(days=max(int(retention_days), 1))
    log_dirs = [APP_DIR / "log", RUNTIME_LOG_DIR, RUNTIME_LOG_DIR / "archive"]

    for directory in log_dirs:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".log", ".txt"} and ".log." not in path.name.lower():
                continue
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if modified_at >= cutoff:
                continue
            try:
                path.unlink()
            except Exception:
                continue


def cleanup_legacy_runtime_cache_dir() -> None:
    runtime_cache_dir = PROJECT_ROOT / ".runtime_cache"
    if not runtime_cache_dir.exists() or not runtime_cache_dir.is_dir():
        return

    for path in sorted(runtime_cache_dir.rglob("*"), reverse=True):
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        except Exception:
            continue

    try:
        runtime_cache_dir.rmdir()
    except Exception:
        pass
