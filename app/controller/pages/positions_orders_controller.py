from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig
from app.views.viewmodels.pages.page_contexts import positions_context


router = APIRouter()

PAGE = PageConfig(
    key="positions_orders",
    template_name="pages/positions_orders.html",
    title="持仓与订单",
    subtitle="统一查看自动套利后的持仓状态、异常订单和最近成交。",
    css_name="positions_orders.css",
    js_name="positions_orders.js",
)


@router.get("/positions-orders", response_class=HTMLResponse)
async def positions_orders_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    return render_page(request, PAGE, current_user=current_user, **positions_context())
