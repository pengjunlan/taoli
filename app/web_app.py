from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.controller.api_controller import router as api_router
from app.controller.page_controller import router as page_router
from app.core.paths import STATIC_DIR


def create_app() -> FastAPI:
    app = FastAPI(
        title="多交易所套利系统",
        description="多交易所套利系统。",
        version="0.1.0",
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(api_router)
    app.include_router(page_router)
    return app
