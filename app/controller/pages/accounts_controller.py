from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig


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

    context = {
        "summary_cards": [
            {"key": "account_count", "label": "参与调度账户", "value": "加载中...", "change": "正在读取账户列表", "tone": "brand"},
            {"key": "total_available", "label": "总可用保证金", "value": "加载中...", "change": "正在汇总账户资金", "tone": "positive"},
            {"key": "imbalance_count", "label": "失衡账户", "value": "加载中...", "change": "正在计算偏差情况", "tone": "warning"},
            {"key": "auto_transfer_status", "label": "自动均衡", "value": "加载中...", "change": "正在读取自动调拨配置", "tone": "neutral"},
        ],
        "balance_rows": [],
        "account_rows": [],
        "address_rows": [],
    }

    return render_page(request, PAGE, current_user=current_user, **context)
