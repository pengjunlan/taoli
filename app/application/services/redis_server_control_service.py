"""Helpers for starting a local redis-server.exe process from the admin page."""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import time
from pathlib import Path

from app.config import redis_config


logger = logging.getLogger(__name__)

SOCKET_PROBE_TIMEOUT_SECONDS = 0.5
STARTUP_WAIT_SECONDS = 10.0
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WINDOWS_REDIS_CANDIDATES = (
    PROJECT_ROOT / "redis-server.exe",
    Path.cwd() / "redis-server.exe",
    PROJECT_ROOT / "redis" / "redis-server.exe",
    Path("C:/Redis/redis-server.exe"),
    Path("C:/Program Files/Redis/redis-server.exe"),
    Path("C:/Program Files/Memurai/redis-server.exe"),
)


class RedisServerControlService:
    def start_server(self) -> dict[str, object]:
        if self.is_available():
            return {
                "success": True,
                "message": "Redis 已经可用，无需重复启动。",
            }

        redis_binary = self._find_windows_redis_binary()
        if redis_binary is None:
            return {
                "success": False,
                "message": (
                    "Redis 启动失败：未找到 redis-server.exe。"
                    "如果它不在系统 PATH 里，请在 .env 里配置 "
                    "ARBI_REDIS_SERVER_PATH=你的 redis-server.exe 绝对路径"
                ),
            }

        if not redis_binary.exists():
            return {
                "success": False,
                "message": f"Redis 启动失败：文件不存在 {redis_binary}",
            }

        try:
            self._start_windows_binary(redis_binary)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis start failed: %s", exc)
            return {
                "success": False,
                "message": f"Redis 启动失败：{exc}",
            }

        if self._wait_until_available():
            return {
                "success": True,
                "message": f"Redis 已启动：{redis_binary}",
            }

        return {
            "success": False,
            "message": f"Redis 启动失败：已执行 {redis_binary.name}，但 {redis_config.host}:{redis_config.port} 未就绪",
        }

    def is_available(self) -> bool:
        return self._probe_socket(redis_config.host, redis_config.port)

    def _wait_until_available(self, timeout_seconds: float = STARTUP_WAIT_SECONDS) -> bool:
        deadline = time.monotonic() + max(timeout_seconds, 1.0)
        while time.monotonic() < deadline:
            if self.is_available():
                return True
            time.sleep(1.0)
        return self.is_available()

    def _probe_socket(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, int(port)), timeout=SOCKET_PROBE_TIMEOUT_SECONDS):
                return True
        except OSError:
            return False

    def _start_windows_binary(self, redis_binary: Path) -> None:
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        subprocess.Popen(
            [
                str(redis_binary),
                "--bind",
                "127.0.0.1",
                "--port",
                str(redis_config.port),
                "--appendonly",
                "no",
            ],
            cwd=str(redis_binary.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def _find_windows_redis_binary(self) -> Path | None:
        if redis_config.server_path:
            configured_path = Path(redis_config.server_path).expanduser()
            return configured_path

        for candidate in WINDOWS_REDIS_CANDIDATES:
            if candidate.exists():
                return candidate

        bundled_root = PROJECT_ROOT / "redis"
        if bundled_root.exists():
            for candidate in bundled_root.glob("*/redis-server.exe"):
                if candidate.exists():
                    return candidate

        which_result = shutil.which("redis-server.exe") or shutil.which("redis-server")
        if which_result:
            resolved = Path(which_result)
            if resolved.exists():
                return resolved
        return None


redis_server_control_service = RedisServerControlService()
