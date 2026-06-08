"""Authentication API routes."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Request, Response

from app.application.dto.requests import LoginRequest, RegisterRequest
from app.application.dto.responses import AuthResponse
from app.application.services import auth_service
from app.config import settings
from app.shared.exceptions import (
    AuthenticationFailedError,
    AuthValidationError,
    UserAlreadyExistsError,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
async def register_api(payload: RegisterRequest) -> Dict[str, object]:
    try:
        auth_service.register(payload)
    except (AuthValidationError, UserAlreadyExistsError) as exc:
        return AuthResponse(success=False, message=str(exc)).to_dict()

    return AuthResponse(
        success=True,
        message="注册成功，请登录。",
        redirect_url="/login",
    ).to_dict()


@router.post("/login")
async def login_api(payload: LoginRequest, request: Request, response: Response) -> Dict[str, object]:
    ip_address = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    try:
        result = auth_service.login(payload, ip_address=ip_address, user_agent=user_agent)
    except (AuthValidationError, AuthenticationFailedError) as exc:
        return AuthResponse(success=False, message=str(exc)).to_dict()

    response.set_cookie(
        key=settings.auth.session_cookie_name,
        value=result.session_token,
        max_age=result.ttl_seconds,
        httponly=True,
        samesite=settings.auth.same_site,
        secure=settings.auth.secure_cookie,
        path="/",
    )
    return AuthResponse(
        success=True,
        message="登录成功。",
        redirect_url="/dashboard",
    ).to_dict()


@router.post("/logout")
async def logout_api(request: Request, response: Response) -> Dict[str, object]:
    session_token = request.cookies.get(settings.auth.session_cookie_name, "")
    auth_service.logout(session_token)
    response.delete_cookie(
        key=settings.auth.session_cookie_name,
        path="/",
    )
    return AuthResponse(
        success=True,
        message="已退出登录。",
        redirect_url="/login",
    ).to_dict()
