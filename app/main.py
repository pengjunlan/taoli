from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.controller.api_controller import router as api_router
from app.controller.page_controller import router as page_router
from app.infrastructure.cache import redis_session_cache
from app.infrastructure.persistence import mysql_manager


BASE_DIR = Path(__file__).resolve().parent

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
    mysql_manager.initialize()
    redis_session_cache.initialize()
