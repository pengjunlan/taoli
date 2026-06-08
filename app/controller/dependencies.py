"""Reusable dependencies for authentication and route protection."""

from __future__ import annotations

from fastapi import HTTPException, Request, WebSocket, status
from fastapi.responses import RedirectResponse
from typing import Optional

from app.application.services import auth_service
from app.config import settings
from app.domain.entities import AuthUser
from app.shared.exceptions import SessionExpiredError


def _read_session_cookie(request: Request) -> str:
    return request.cookies.get(settings.auth.session_cookie_name, "").strip()


def get_optional_current_user(request: Request) -> Optional[AuthUser]:
    session_token = _read_session_cookie(request)
    if not session_token:
        return None

    try:
        return auth_service.resolve_user_from_session(session_token)
    except SessionExpiredError:
        return None


def require_current_user(request: Request) -> AuthUser:
    user = get_optional_current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录。")
    return user


def require_api_user(request: Request) -> AuthUser:
    return require_current_user(request)


def require_page_user(request: Request) -> AuthUser:
    user = get_optional_current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录。")
    return user


async def enforce_websocket_auth(websocket: WebSocket) -> Optional[AuthUser]:
    session_token = websocket.cookies.get(settings.auth.session_cookie_name, "").strip()
    if not session_token:
        await websocket.close(code=1008, reason="unauthorized")
        return None

    try:
        return auth_service.resolve_user_from_session(session_token)
    except SessionExpiredError:
        await websocket.close(code=1008, reason="session_expired")
        return None


def redirect_if_authenticated(request: Request, target: str = "/dashboard") -> Optional[RedirectResponse]:
    if get_optional_current_user(request) is None:
        return None
    return RedirectResponse(url=target, status_code=302)
