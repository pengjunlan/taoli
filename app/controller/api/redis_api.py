"""Admin Redis inspection APIs."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends

from app.application.services.redis_inspector_service import redis_inspector_service
from app.application.services.redis_server_control_service import redis_server_control_service
from app.controller.dependencies import require_admin_user
from app.domain.entities import AuthUser


router = APIRouter()


@router.get("/api/redis/overview")
async def redis_overview_api(
    current_user: AuthUser = Depends(require_admin_user),
) -> Dict[str, object]:
    _ = current_user
    snapshot = redis_inspector_service.build_snapshot()
    return {
        "success": True,
        "message": "Redis 缓存数据读取成功",
        **snapshot,
    }


@router.post("/api/redis/start")
async def redis_start_api(
    current_user: AuthUser = Depends(require_admin_user),
) -> Dict[str, object]:
    _ = current_user
    result = redis_server_control_service.start_server()
    return result
