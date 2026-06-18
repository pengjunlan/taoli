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
    subtitle="统一查看正在套利中的组合、当前挂单与实际订单，以及历史订单和真实持仓运行情况。",
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
