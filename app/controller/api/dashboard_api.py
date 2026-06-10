"""Dashboard API routes."""

from typing import Dict

from fastapi import APIRouter, Depends

from app.application.services import dashboard_service
from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser


router = APIRouter()


@router.get("/api/dashboard")
async def dashboard_api(current_user: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    return dashboard_service.build_payload_for_user(current_user)
