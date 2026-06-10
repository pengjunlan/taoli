"""Opportunity list API routes."""

from typing import Dict, List

from fastapi import APIRouter, Depends

from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser
from app.infrastructure.cache import market_runtime_cache


router = APIRouter()


@router.get("/api/funding-opportunities")
async def funding_api(current_user: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    rows: List[dict] = market_runtime_cache.get_user_rows("funding", current_user.id)
    return {
        "success": True,
        "channel": "funding",
        "message": "资金费套利机会读取成功。",
        "opportunity_count": len(rows),
        "rows": rows,
    }


@router.get("/api/spread-opportunities")
async def spread_api(current_user: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    rows: List[dict] = market_runtime_cache.get_user_rows("spread", current_user.id)
    return {
        "success": True,
        "channel": "spread",
        "message": "价差套利机会读取成功。",
        "opportunity_count": len(rows),
        "rows": rows,
    }
