"""Opportunity list API routes."""

import logging
from typing import Dict

from fastapi import APIRouter, Depends, Query

from app.application.services import opportunity_status_service, strategy_runtime_service
from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser
from app.shared.exceptions import AccountError, AccountNotFoundError, AccountValidationError


router = APIRouter()
logger = logging.getLogger(__name__)


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


@router.post("/api/strategy-runtime/{execution_id}/close")
async def strategy_runtime_close_api(
    execution_id: int,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = strategy_runtime_service.request_close_execution(
            user_id=current_user.id,
            execution_id=execution_id,
        )
    except (AccountNotFoundError, AccountValidationError) as exc:
        return {"success": False, "message": str(exc)}
    except AccountError as exc:
        return {"success": False, "message": str(exc)}
    except Exception:
        logger.exception(
            "Create manual close execution failed unexpectedly for user_id=%s execution_id=%s",
            current_user.id,
            execution_id,
        )
        return {"success": False, "message": "发起一键平仓失败：服务内部异常，请查看后端日志。"}

    return {
        "success": True,
        "message": "该组合已经在平仓中。" if bool(result.get("already_pending")) else "已发起一键平仓，后台开始执行。",
        **result,
    }
