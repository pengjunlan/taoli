from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import redirect_if_authenticated
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig


router = APIRouter()

PAGE = PageConfig(
    key="login",
    template_name="pages/login.html",
    title="大宝-套利系统登录",
    subtitle="请输入账号和密码。",
    css_name="login.css",
    js_name="login.js",
    show_shell=False,
)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    redirect_response = redirect_if_authenticated(request)
    if redirect_response is not None:
        return redirect_response
    return render_page(request, PAGE)
