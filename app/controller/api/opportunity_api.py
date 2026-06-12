"""Opportunity list API routes."""

from typing import Dict

from fastapi import APIRouter, Depends, Query

from app.application.services import opportunity_status_service, strategy_runtime_service
from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser


router = APIRouter()


@router.get("/api/funding-opportunities")
async def funding_api(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=20),
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    payload = opportunity_status_service.build_channel_payload(
        channel="funding",
        user_id=current_user.id,
        page=page,
        page_size=page_size,
    )
    return {
        "success": True,
        "channel": str(payload.get("channel") or "funding"),
        "message": "资金费套利机会读取成功。",
        "opportunity_count": int(payload.get("opportunity_count") or 0),
        "page": int(payload.get("page") or 1),
        "page_size": int(payload.get("page_size") or 5),
        "page_count": int(payload.get("page_count") or 1),
        "rows": list(payload.get("rows") or []),
        "runtime_status": payload.get("runtime_status"),
        "diagnostics": payload.get("diagnostics"),
    }


@router.get("/api/spread-opportunities")
async def spread_api(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=20),
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    payload = opportunity_status_service.build_channel_payload(
        channel="spread",
        user_id=current_user.id,
        page=page,
        page_size=page_size,
    )
    return {
        "success": True,
        "channel": str(payload.get("channel") or "spread"),
        "message": "价差套利机会读取成功。",
        "opportunity_count": int(payload.get("opportunity_count") or 0),
        "page": int(payload.get("page") or 1),
        "page_size": int(payload.get("page_size") or 5),
        "page_count": int(payload.get("page_count") or 1),
        "rows": list(payload.get("rows") or []),
        "runtime_status": payload.get("runtime_status"),
        "diagnostics": payload.get("diagnostics"),
    }


@router.get("/api/strategy-runtime")
async def strategy_runtime_api(current_user: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    payload = strategy_runtime_service.get_positions_orders_payload(current_user.id)
    return {
        "success": True,
        "message": "策略运行态读取成功。",
        **payload,
    }
