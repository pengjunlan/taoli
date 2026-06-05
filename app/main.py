from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.controller.api_controller import router as api_router
from app.controller.page_controller import router as page_router


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
