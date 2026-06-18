from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig


router = APIRouter()

PAGE = PageConfig(
    key="redis_inspector",
    template_name="pages/redis_inspector.html",
    title="Redis 监控",
    subtitle="查看当前 Redis 中的运行时缓存、会话缓存和线程状态缓存，按分组结构化展示。",
    css_name="redis_inspector.css",
    js_name="redis_inspector.js",
)


@router.get("/redis-inspector", response_class=HTMLResponse)
async def redis_inspector_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None or not current_user.is_admin:
        return RedirectResponse(url="/login", status_code=302)

    return render_page(
        request,
        PAGE,
        current_user=current_user,
        summary_cards=[
            {
                "key": "redis_status",
                "label": "Redis 连接",
                "value": "加载中...",
                "change": "正在检测当前 Redis 连接状态",
                "tone": "brand",
            },
            {
                "key": "redis_keys",
                "label": "缓存键数量",
                "value": "加载中...",
                "change": "正在统计可展示的 Redis 键",
                "tone": "brand",
            },
            {
                "key": "runtime_keys",
                "label": "运行时键",
                "value": "加载中...",
                "change": "正在统计 runtime 命名空间键",
                "tone": "positive",
            },
            {
                "key": "session_keys",
                "label": "会话键",
                "value": "加载中...",
                "change": "正在统计登录会话缓存键",
                "tone": "warning",
            },
        ],
    )
