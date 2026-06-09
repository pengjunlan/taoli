from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import redirect_if_authenticated
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig


router = APIRouter()

PAGE = PageConfig(
    key="register",
    template_name="pages/register.html",
    title="注册账号",
    subtitle="填写账号信息完成注册。",
    css_name="register.css",
    js_name="register.js",
    show_shell=False,
)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    redirect_response = redirect_if_authenticated(request)
    if redirect_response is not None:
        return redirect_response
    return render_page(request, PAGE)
