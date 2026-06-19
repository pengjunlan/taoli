"""Admin Redis inspection APIs."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, Query

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
    snapshot = redis_inspector_service.build_overview()
    return {
        "success": True,
        "message": "Redis 缓存概览读取成功",
        **snapshot,
    }


@router.get("/api/redis/group")
async def redis_group_api(
    group_key: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: AuthUser = Depends(require_admin_user),
) -> Dict[str, object]:
    _ = current_user
    payload = redis_inspector_service.build_group_page(
        group_key=group_key,
        page=page,
        page_size=page_size,
    )
    return {
        "success": True,
        "message": "Redis 分组数据读取成功",
        **payload,
    }


@router.post("/api/redis/start")
async def redis_start_api(
    current_user: AuthUser = Depends(require_admin_user),
) -> Dict[str, object]:
    _ = current_user
    result = redis_server_control_service.start_server()
    return result
