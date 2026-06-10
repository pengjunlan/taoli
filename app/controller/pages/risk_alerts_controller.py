from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig


router = APIRouter()

PAGE = PageConfig(
    key="risk_alerts",
    template_name="pages/risk_alerts.html",
    title="线程监控中心",
    subtitle="集中查看后台常驻线程的运行状态、心跳、异常和最近日志。",
    css_name="risk_alerts.css",
    js_name="risk_alerts.js",
)


@router.get("/risk-alerts", response_class=HTMLResponse)
async def risk_alerts_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)

    return render_page(
        request,
        PAGE,
        current_user=current_user,
    )
