from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.application.services import strategy_runtime_service
from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig


router = APIRouter()

PAGE = PageConfig(
    key="positions_orders",
    template_name="pages/positions_orders.html",
    title="策略运行监控",
    subtitle="统一查看规则命中后的候选持仓、候选执行记录，以及后续真实成交回报接入情况。",
    css_name="positions_orders.css",
    js_name="positions_orders.js",
)


@router.get("/positions-orders", response_class=HTMLResponse)
async def positions_orders_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)

    payload = strategy_runtime_service.get_positions_orders_payload(current_user.id)
    return render_page(request, PAGE, current_user=current_user, **payload)
