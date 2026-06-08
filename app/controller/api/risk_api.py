"""Risk API route placeholders."""

from typing import Dict

from fastapi import APIRouter, Depends

from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser

router = APIRouter()


@router.get("/api/risk/status")
async def risk_status_api(_: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    return {
        "success": True,
        "message": "风控接口已登录，可访问。",
    }
