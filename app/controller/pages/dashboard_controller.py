from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig
from app.views.viewmodels.pages.page_contexts import dashboard_context


router = APIRouter()

PAGE = PageConfig(
    key="dashboard",
    template_name="pages/dashboard.html",
    title="多交易所套利总览",
    subtitle="统一查看自动监控、可执行机会和关键风险状态。",
    css_name="dashboard.css",
    js_name="dashboard.js",
)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    return render_page(request, PAGE, current_user=current_user, **dashboard_context())
