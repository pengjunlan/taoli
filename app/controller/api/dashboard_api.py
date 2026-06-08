"""Dashboard API routes."""

from typing import Dict

from fastapi import APIRouter, Depends

from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser
from app.views.presenters.api_presenters.prototype_payloads import build_dashboard_payload


router = APIRouter()


@router.get("/api/dashboard")
async def dashboard_api(_: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    return build_dashboard_payload()
