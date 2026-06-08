"""Account API routes."""

from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Depends

from app.application.dto.requests import AccountCreateRequest, AccountUpdateRequest
from app.application.dto.responses import AccountResponse
from app.application.services import account_service
from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser
from app.shared.exceptions import AccountError, AccountNotFoundError, AccountValidationError

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/accounts/status")
async def account_status_api(_: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    return {
        "success": True,
        "message": "账户接口已登录，可访问。",
    }


@router.get("/api/accounts/list")
async def account_list_api(
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    account_rows = account_service.build_account_rows_for_user(current_user.id)
    address_rows = account_service.build_address_rows_for_user(current_user.id)
    return {
        "success": True,
        "message": "账户列表读取成功。",
        "account_rows": account_rows,
        "address_rows": address_rows,
        "account_count": len(account_rows),
        "address_count": len(address_rows),
    }


@router.post("/api/accounts")
async def create_account_api(
    payload: AccountCreateRequest,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = account_service.create_account(payload, current_user)
    except AccountValidationError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception("Create account failed unexpectedly for user_id=%s", current_user.id)
        return AccountResponse(success=False, message="保存账户失败：服务内部异常，请查看后端日志。").to_dict()

    return AccountResponse(
        success=True,
        message="账户已保存。",
        account_id=result.account.id,
    ).to_dict()


@router.get("/api/accounts/{account_id}")
async def get_account_api(
    account_id: int,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = account_service.get_account_detail(account_id, current_user)
    except AccountNotFoundError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception(
            "Get account failed unexpectedly for user_id=%s account_id=%s",
            current_user.id,
            account_id,
        )
        return AccountResponse(success=False, message="读取账户失败：服务内部异常，请查看后端日志。").to_dict()

    return {
        "success": True,
        "message": "账户读取成功。",
        "account": {
            "account_id": result.account_id,
            "market_type": result.market_type,
            "exchange_code": result.exchange_code,
            "api_key": result.api_key,
            "api_secret": result.api_secret,
            "api_passphrase": result.api_passphrase,
            "address_network": result.address_network,
            "address_value": result.address_value,
            "address_memo": result.address_memo,
        },
    }


@router.post("/api/accounts/{account_id}")
async def update_account_api(
    account_id: int,
    payload: AccountUpdateRequest,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = account_service.update_account(account_id, payload, current_user)
    except AccountValidationError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception(
            "Update account failed unexpectedly for user_id=%s account_id=%s",
            current_user.id,
            account_id,
        )
        return AccountResponse(success=False, message="更新账户失败：服务内部异常，请查看后端日志。").to_dict()

    return AccountResponse(
        success=True,
        message="账户已更新。",
        account_id=result.account.id,
    ).to_dict()


@router.post("/api/accounts/{account_id}/delete")
async def delete_account_api(
    account_id: int,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        account_service.delete_account(account_id, current_user)
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception(
            "Delete account failed unexpectedly for user_id=%s account_id=%s",
            current_user.id,
            account_id,
        )
        return AccountResponse(success=False, message="删除账户失败：服务内部异常，请查看后端日志。").to_dict()

    return AccountResponse(success=True, message="账户已删除。").to_dict()
