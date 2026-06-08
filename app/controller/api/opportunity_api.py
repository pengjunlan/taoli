"""Opportunity list API routes."""

from typing import Dict

from fastapi import APIRouter, Depends

from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser
from app.views.presenters.api_presenters.prototype_payloads import (
    build_funding_payload,
    build_spread_payload,
)


router = APIRouter()


@router.get("/api/funding-opportunities")
async def funding_api(_: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    return build_funding_payload()


@router.get("/api/spread-opportunities")
async def spread_api(_: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    return build_spread_payload()
