from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig
from app.views.viewmodels.pages.page_contexts import strategy_context


router = APIRouter()

PAGE = PageConfig(
    key="strategy_list",
    template_name="pages/strategy_list.html",
    title="自动规则管理",
    subtitle="管理全局自动执行规则组，而不是逐个交易对手工建策略。",
    css_name="strategy_list.css",
    js_name="strategy_list.js",
)


@router.get("/strategies", response_class=HTMLResponse)
async def strategy_list_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    return render_page(request, PAGE, current_user=current_user, **strategy_context())
