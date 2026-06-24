from __future__ import annotations

import argparse
from typing import Sequence

from app.bootstrap import initialize_process_environment, initialize_runtime_dependencies
from app.runtime import (
    run_all as runtime_run_all,
    run_web as runtime_run_web,
    run_worker as runtime_run_worker,
    should_spawn_worker_on_startup,
    spawn_worker_process,
    stop_worker_process,
)
from app.web_app import create_app


initialize_process_environment()

app = create_app()


@app.on_event("startup")
async def startup_event() -> None:
    initialize_runtime_dependencies(include_session_cache=True)
    if should_spawn_worker_on_startup():
        spawn_worker_process()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if should_spawn_worker_on_startup():
        stop_worker_process()


def run_web(*, host: str, port: int, spawn_worker: bool = False) -> None:
    runtime_run_web(app, host=host, port=port, spawn_worker=spawn_worker)


def run_worker() -> None:
    runtime_run_worker()


def run_all(*, host: str, port: int) -> None:
    runtime_run_all(app, host=host, port=port)


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
