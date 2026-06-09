from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig
from app.views.viewmodels.pages.page_contexts import funding_rows


router = APIRouter()

PAGE = PageConfig(
    key="funding_arbitrage",
    template_name="pages/funding_arbitrage.html",
    title="资费套利",
    subtitle="自动扫描已配置交易所中的资金费机会，命中统一规则后直接进入套利执行。",
    css_name="funding_arbitrage.css",
    js_name="funding_arbitrage.js",
)


@router.get("/funding-arbitrage", response_class=HTMLResponse)
async def funding_arbitrage_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    return render_page(request, PAGE, current_user=current_user, rows=funding_rows())
