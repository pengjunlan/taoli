"""Helpers for organizing runtime log files."""

from __future__ import annotations

from pathlib import Path

from app.core.paths import APP_DIR, PROJECT_ROOT, RUNTIME_LOG_DIR


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
