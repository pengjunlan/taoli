"""Account API routes."""

from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Depends

from app.application.dto.requests import (
    AccountAutoTransferConfigRequest,
    AccountCreateRequest,
    AccountFundingRatioUpdateRequest,
    AccountTransferCreateRequest,
    AccountUpdateRequest,
    ExchangeConnectionTestRequest,
    ExchangeAssetNetworksRefreshRequest,
)
from app.application.dto.responses import AccountResponse
from app.application.services import account_service, exchange_connection_service
from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser
from app.shared.exceptions import (
    AccountError,
    AccountNotFoundError,
    AccountValidationError,
    ExchangeError,
    ExchangeValidationError,
)

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
    auto_transfer_config = account_service.get_auto_transfer_config(current_user.id)
    balance_rows = account_service.build_balance_rows_from_accounts(account_rows, auto_transfer_config.trigger_ratio)
    auto_transfer_alert = account_service.build_auto_transfer_alert_for_user(current_user.id)
    summary_cards = account_service.build_summary_cards(
        account_rows,
        balance_rows,
        is_auto_transfer_enabled=auto_transfer_config.is_enabled,
    )
    return {
        "success": True,
        "message": "账户列表读取成功。",
        "account_rows": account_rows,
        "address_rows": address_rows,
        "balance_rows": balance_rows,
        "summary_cards": summary_cards,
        "account_count": len(account_rows),
        "address_count": len(address_rows),
        "auto_transfer_alert": auto_transfer_alert,
        "auto_transfer_config": {
            "is_enabled": auto_transfer_config.is_enabled,
            "trigger_ratio": auto_transfer_config.trigger_ratio,
        },
    }


@router.post("/api/accounts/transfer")
async def create_account_transfer_api(
    payload: AccountTransferCreateRequest,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = account_service.create_transfer_record(payload, current_user)
    except AccountValidationError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception(
            "Create transfer record failed unexpectedly for user_id=%s from_account_id=%s to_account_id=%s",
            current_user.id,
            payload.from_account_id,
            payload.to_account_id,
        )
        return AccountResponse(success=False, message="保存调拨记录失败：服务内部异常，请查看后端日志。").to_dict()

    return {
        "success": True,
        "message": "真实调拨任务已创建，后台开始执行。",
        "transfer_id": result.transfer_record.id,
    }


@router.get("/api/accounts/{account_id}/transfer-options")
async def get_account_transfer_options_api(
    account_id: int,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = account_service.build_transfer_options_for_user(account_id, current_user.id)
    except AccountNotFoundError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception(
            "Get transfer options failed unexpectedly for user_id=%s account_id=%s",
            current_user.id,
            account_id,
        )
        return AccountResponse(success=False, message="读取可执行调拨目标失败：服务内部异常，请查看后端日志。").to_dict()

    return {
        "success": True,
        "message": "可执行调拨目标读取成功。",
        "from_account_id": result["from_account_id"],
        "from_account_name": result["from_account_name"],
        "options": result["options"],
        "option_count": result["option_count"],
        "blocked_count": result["blocked_count"],
        "notice": result["notice"],
    }


@router.get("/api/accounts/auto-transfer-config")
async def get_auto_transfer_config_api(
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    config = account_service.get_auto_transfer_config(current_user.id)
    return {
        "success": True,
        "message": "自动调拨配置读取成功。",
        "config": {
            "is_enabled": config.is_enabled,
            "trigger_ratio": config.trigger_ratio,
        },
    }


@router.post("/api/accounts/auto-transfer-config")
async def update_auto_transfer_config_api(
    payload: AccountAutoTransferConfigRequest,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        config = account_service.update_auto_transfer_config(
            current_user,
            is_enabled=payload.is_enabled,
            trigger_ratio=payload.trigger_ratio,
        )
    except AccountValidationError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception("Update auto transfer config failed unexpectedly for user_id=%s", current_user.id)
        return AccountResponse(success=False, message="保存自动调拨配置失败：服务内部异常，请查看后端日志。").to_dict()

    return {
        "success": True,
        "message": "自动调拨配置已保存。",
        "config": {
            "is_enabled": config.is_enabled,
            "trigger_ratio": config.trigger_ratio,
        },
        "auto_transfer_executed": False,
        "transfer_id": None,
    }


@router.post("/api/accounts/{account_id}/auto-transfer-unlock")
async def unlock_auto_transfer_account_api(
    account_id: int,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        account_service.unlock_auto_transfer_account(current_user.id, account_id)
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception(
            "Unlock auto transfer account failed unexpectedly for user_id=%s account_id=%s",
            current_user.id,
            account_id,
        )
        return AccountResponse(success=False, message="解冻自动调拨失败：服务内部异常，请查看后端日志。").to_dict()

    return AccountResponse(success=True, message="该账户自动调拨已解冻。", account_id=account_id).to_dict()


@router.post("/api/accounts/auto-transfer/execute")
async def execute_auto_transfer_api(
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = account_service.execute_auto_transfer(current_user)
    except AccountValidationError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception("Execute auto transfer failed unexpectedly for user_id=%s", current_user.id)
        return AccountResponse(success=False, message="执行自动调拨失败：服务内部异常，请查看后端日志。").to_dict()

    return {
        "success": True,
        "message": "自动真实调拨任务已创建，后台开始执行。",
        "transfer_id": result.transfer_record.id,
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
            "connection_test_status": result.connection_test_status,
            "address_network": result.address_network,
            "address_value": result.address_value,
            "address_memo": result.address_memo,
        },
        "network_options": account_service.list_exchange_network_options(result.exchange_code),
    }


@router.get("/api/accounts/exchanges/{exchange_code}/networks")
async def list_exchange_network_options_api(
    exchange_code: str,
    _: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = account_service.list_exchange_network_options(exchange_code)
    except AccountValidationError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception("List exchange network options failed unexpectedly for exchange_code=%s", exchange_code)
        return AccountResponse(success=False, message="读取交易所网络失败：服务内部异常，请查看后端日志。").to_dict()

    return {
        "success": True,
        "message": "交易所网络读取成功。",
        **result,
    }


@router.post("/api/accounts/exchanges/networks/refresh")
async def refresh_exchange_network_options_api(
    payload: ExchangeAssetNetworksRefreshRequest,
    _: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = account_service.refresh_exchange_network_options(
            payload.exchange_code,
            market_type=payload.market_type,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            api_passphrase=payload.api_passphrase,
        )
    except AccountValidationError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception("Refresh exchange network options failed unexpectedly for exchange_code=%s", payload.exchange_code)
        return AccountResponse(success=False, message="更新交易所网络失败：服务内部异常，请查看后端日志。").to_dict()

    return {
        "success": True,
        "message": "交易所网络已更新。",
        **result,
    }


@router.post("/api/accounts/test-connection")
async def test_account_connection_api(
    payload: ExchangeConnectionTestRequest,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    account_id = payload.account_id

    try:
        exchange_connection_service.test_connection(payload)
        if account_id:
            account_service.mark_connection_test_status(account_id, current_user, "success")
    except ExchangeValidationError as exc:
        if account_id:
            try:
                account_service.mark_connection_test_status(account_id, current_user, "failed")
            except AccountError:
                logger.exception("Failed to persist failed connection test status for account_id=%s", account_id)
        return {"success": False, "message": str(exc)}
    except ExchangeError as exc:
        if account_id:
            try:
                account_service.mark_connection_test_status(account_id, current_user, "failed")
            except AccountError:
                logger.exception("Failed to persist failed connection test status for account_id=%s", account_id)
        return {"success": False, "message": str(exc)}
    except AccountError as exc:
        return {"success": False, "message": str(exc)}
    except Exception:
        logger.exception("Test exchange connection failed unexpectedly")
        if account_id:
            try:
                account_service.mark_connection_test_status(account_id, current_user, "failed")
            except AccountError:
                logger.exception("Failed to persist failed connection test status for account_id=%s", account_id)
        return {"success": False, "message": "测试连接失败：服务内部异常，请查看后端日志。"}

    return {
        "success": True,
        "message": "连接成功，可保存账户。",
        "connection_test_status": "success",
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


@router.post("/api/accounts/{account_id}/funding-ratio")
async def update_account_funding_ratio_api(
    account_id: int,
    payload: AccountFundingRatioUpdateRequest,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        account_service.update_funding_ratio_percent(account_id, current_user, payload.funding_ratio_percent)
    except AccountValidationError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except AccountError as exc:
        return AccountResponse(success=False, message=str(exc)).to_dict()
    except Exception:
        logger.exception(
            "Update funding ratio failed unexpectedly for user_id=%s account_id=%s",
            current_user.id,
            account_id,
        )
        return AccountResponse(success=False, message="更新资金占比失败：服务内部异常，请查看后端日志。").to_dict()

    return AccountResponse(success=True, message="资金占比已保存。", account_id=account_id).to_dict()


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
