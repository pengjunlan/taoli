"""System exchange config APIs."""

from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Depends

from app.application.dto.requests import SystemExchangeConfigUpdateRequest
from app.application.services import system_exchange_config_service
from app.controller.dependencies import require_admin_user
from app.domain.entities import AuthUser
from app.shared.exceptions import AccountError, AccountValidationError


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/system-exchanges/list")
async def system_exchange_list_api(
    current_user: AuthUser = Depends(require_admin_user),
) -> Dict[str, object]:
    _ = current_user
    rows = system_exchange_config_service.list_config_rows()
    summary_cards = system_exchange_config_service.build_summary_cards(rows)
    return {
        "success": True,
        "message": "系统交易所配置读取成功",
        "summary_cards": summary_cards,
        "config_rows": rows,
        "config_count": len(rows),
    }


@router.get("/api/system-exchanges/{exchange_code}")
async def system_exchange_detail_api(
    exchange_code: str,
    current_user: AuthUser = Depends(require_admin_user),
) -> Dict[str, object]:
    _ = current_user
    row = system_exchange_config_service.get_config_detail(exchange_code)
    if row is None:
        return {"success": False, "message": "未找到该系统交易所配置"}

    return {
        "success": True,
        "message": "系统交易所配置读取成功",
        "config": row,
    }


@router.get("/api/system-exchanges/{exchange_code}/swap-symbols")
async def system_exchange_swap_symbols_api(
    exchange_code: str,
    current_user: AuthUser = Depends(require_admin_user),
) -> Dict[str, object]:
    _ = current_user
    payload = system_exchange_config_service.list_swap_symbols(exchange_code)
    if payload is None:
        return {"success": False, "message": "未找到该系统交易所配置"}

    return {
        "success": True,
        "message": "系统交易所永续交易对读取成功",
        **payload,
    }


@router.post("/api/system-exchanges/{exchange_code}/swap-symbols/refresh")
async def system_exchange_refresh_swap_symbols_api(
    exchange_code: str,
    current_user: AuthUser = Depends(require_admin_user),
) -> Dict[str, object]:
    _ = current_user
    try:
        payload = system_exchange_config_service.refresh_swap_symbols(exchange_code)
    except Exception as exc:
        logger.exception("Refresh system exchange swap symbols failed: exchange_code=%s", exchange_code)
        return {"success": False, "message": str(exc)}

    if payload is None:
        return {"success": False, "message": "未找到该系统交易所配置"}

    return {
        "success": True,
        "message": "永续交易对更新成功",
        **payload,
    }


@router.post("/api/system-exchanges")
async def system_exchange_update_api(
    payload: SystemExchangeConfigUpdateRequest,
    current_user: AuthUser = Depends(require_admin_user),
) -> Dict[str, object]:
    try:
        row = system_exchange_config_service.update_config(payload, current_user)
    except AccountValidationError as exc:
        return {"success": False, "message": str(exc)}
    except AccountError as exc:
        return {"success": False, "message": str(exc)}
    except Exception:
        logger.exception(
            "Update system exchange config failed unexpectedly for user_id=%s exchange_code=%s",
            current_user.id,
            payload.exchange_code,
        )
        return {"success": False, "message": "保存系统交易所配置失败：服务内部异常，请查看后端日志"}

    return {
        "success": True,
        "message": "系统交易所配置已保存",
        "config": row,
    }
