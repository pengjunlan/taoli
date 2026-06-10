"""Risk and worker monitor APIs."""

from typing import Dict, List

from fastapi import APIRouter, Depends

from app.application.services import monitor_center_service
from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser


router = APIRouter()


@router.get("/api/risk/status")
async def risk_status_api(_: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    return {
        "success": True,
        "message": "线程监控接口可用。",
    }


@router.get("/api/risk/workers")
async def risk_workers_api(_: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    workers: List[dict] = monitor_center_service.snapshot()
    running_count = sum(1 for item in workers if item.get("status") == "running")
    error_count = sum(1 for item in workers if item.get("status") == "error")

    return {
        "success": True,
        "message": "线程监控数据获取成功。",
        "summary": {
            "worker_count": len(workers),
            "running_count": running_count,
            "error_count": error_count,
        },
        "workers": workers,
    }
