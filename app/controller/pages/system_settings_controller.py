from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig


router = APIRouter()

PAGE = PageConfig(
    key="system_settings",
    template_name="pages/system_settings.html",
    title="系统配置",
    subtitle="配置系统级交易所连接方式，统一控制公共市场数据同步所使用的交易所接口。",
    css_name="system_settings.css",
    js_name="system_settings.js",
)


@router.get("/system-settings", response_class=HTMLResponse)
async def system_settings_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)

    return render_page(
        request,
        PAGE,
        current_user=current_user,
        summary_cards=[
            {
                "key": "exchange_count",
                "label": "交易所数量",
                "value": "加载中...",
                "change": "正在读取系统交易所配置",
                "tone": "brand",
            },
            {
                "key": "enabled_count",
                "label": "已启用",
                "value": "加载中...",
                "change": "正在统计启用配置",
                "tone": "positive",
            },
            {
                "key": "mode_count",
                "label": "私有模式",
                "value": "加载中...",
                "change": "正在统计接口模式",
                "tone": "brand",
            },
            {
                "key": "ready_count",
                "label": "已配置密钥",
                "value": "加载中...",
                "change": "正在统计系统 API 配置",
                "tone": "warning",
            },
        ],
    )
