"""Opportunity runtime diagnostics APIs."""

from typing import Dict

from fastapi import APIRouter, Depends

from app.application.services import opportunity_status_service
from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser


router = APIRouter()


@router.get("/api/opportunity-runtime/overview")
async def opportunity_runtime_overview_api(_: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    overview = opportunity_status_service.build_runtime_overview()
    return {
        "success": True,
        "message": "机会运行态诊断读取成功。",
        **overview,
    }

