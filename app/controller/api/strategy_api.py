"""Strategy rule APIs."""

from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Depends

from app.application.dto.requests import StrategyRuleCreateRequest, StrategyRuleUpdateRequest
from app.application.services import strategy_rule_service
from app.controller.dependencies import require_api_user
from app.domain.entities import AuthUser
from app.shared.exceptions import AccountError, AccountNotFoundError, AccountValidationError


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/strategies/list")
async def strategy_rule_list_api(current_user: AuthUser = Depends(require_api_user)) -> Dict[str, object]:
    rule_rows = strategy_rule_service.list_rules_for_user(current_user.id)
    summary_cards = strategy_rule_service.build_summary_cards(rule_rows)
    return {
        "success": True,
        "message": "规则列表读取成功。",
        "summary_cards": summary_cards,
        "rule_rows": rule_rows,
        "rule_count": len(rule_rows),
    }


@router.get("/api/strategies/{rule_id}")
async def strategy_rule_detail_api(
    rule_id: int,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        rule = strategy_rule_service.get_rule_detail(rule_id, current_user)
    except AccountNotFoundError as exc:
        return {"success": False, "message": str(exc)}
    except AccountError as exc:
        return {"success": False, "message": str(exc)}
    except Exception:
        logger.exception("Get strategy rule failed unexpectedly for user_id=%s rule_id=%s", current_user.id, rule_id)
        return {"success": False, "message": "读取规则失败：服务内部异常，请查看后端日志。"}

    return {
        "success": True,
        "message": "规则读取成功。",
        "rule": rule,
    }


@router.post("/api/strategies")
async def create_strategy_rule_api(
    payload: StrategyRuleCreateRequest,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = strategy_rule_service.create_rule(payload, current_user)
    except AccountValidationError as exc:
        return {"success": False, "message": str(exc)}
    except AccountError as exc:
        return {"success": False, "message": str(exc)}
    except Exception:
        logger.exception("Create strategy rule failed unexpectedly for user_id=%s", current_user.id)
        return {"success": False, "message": "保存规则失败：服务内部异常，请查看后端日志。"}

    return {
        "success": True,
        "message": "规则已保存。",
        "rule_id": result.rule.id,
    }


@router.post("/api/strategies/{rule_id}")
async def update_strategy_rule_api(
    rule_id: int,
    payload: StrategyRuleUpdateRequest,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        result = strategy_rule_service.update_rule(rule_id, payload, current_user)
    except AccountValidationError as exc:
        return {"success": False, "message": str(exc)}
    except AccountError as exc:
        return {"success": False, "message": str(exc)}
    except Exception:
        logger.exception("Update strategy rule failed unexpectedly for user_id=%s rule_id=%s", current_user.id, rule_id)
        return {"success": False, "message": "更新规则失败：服务内部异常，请查看后端日志。"}

    return {
        "success": True,
        "message": "规则已更新。",
        "rule_id": result.rule.id,
    }


@router.post("/api/strategies/{rule_id}/delete")
async def delete_strategy_rule_api(
    rule_id: int,
    current_user: AuthUser = Depends(require_api_user),
) -> Dict[str, object]:
    try:
        strategy_rule_service.delete_rule(rule_id, current_user)
    except AccountError as exc:
        return {"success": False, "message": str(exc)}
    except Exception:
        logger.exception("Delete strategy rule failed unexpectedly for user_id=%s rule_id=%s", current_user.id, rule_id)
        return {"success": False, "message": "删除规则失败：服务内部异常，请查看后端日志。"}

    return {
        "success": True,
        "message": "规则已删除。",
    }
