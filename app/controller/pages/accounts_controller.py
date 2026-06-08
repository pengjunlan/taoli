from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig
from app.views.viewmodels.pages.page_contexts import accounts_context


router = APIRouter()

PAGE = PageConfig(
    key="accounts",
    template_name="pages/accounts.html",
    title="账户与资金调度",
    subtitle="统一管理交易所账户、资金均衡、一键分配和自动失衡修复。",
    css_name="accounts.css",
    js_name="accounts.js",
)


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    return render_page(request, PAGE, current_user=current_user, **accounts_context(user_id=current_user.id))
