from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig


router = APIRouter()

PAGE = PageConfig(
    key="dashboard",
    template_name="pages/dashboard.html",
    title="多交易所套利总览",
    subtitle="统一查看账户资金、可执行机会和后台线程运行状态。",
    css_name="dashboard.css",
    js_name="dashboard.js",
)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)

    return render_page(
        request,
        PAGE,
        current_user=current_user,
        summary_cards=[
            {"key": "total_available", "label": "总可用资金", "value": "加载中...", "change": "正在汇总账户资金", "tone": "positive"},
            {"key": "opportunity_count", "label": "可执行机会", "value": "加载中...", "change": "正在读取机会缓存", "tone": "brand"},
            {"key": "connected_accounts", "label": "已通过连接测试", "value": "加载中...", "change": "正在统计账户状态", "tone": "neutral"},
            {"key": "worker_status", "label": "后台线程状态", "value": "加载中...", "change": "正在读取线程监控", "tone": "warning"},
        ],
        dashboard_rows=[],
    )
