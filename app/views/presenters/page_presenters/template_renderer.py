"""Shared template rendering adapter for page responses."""

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.paths import TEMPLATES_DIR
from app.views.viewmodels.navigation import APP_NAME, build_nav_items
from app.views.viewmodels.page_models import PageConfig


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render_page(request: Request, page: PageConfig, **context: Any) -> HTMLResponse:
    return templates.TemplateResponse(
        page.template_name,
        {
            "request": request,
            "app_name": APP_NAME,
            "page_key": page.key,
            "page_title": page.title,
            "page_subtitle": page.subtitle,
            "page_css": page.css_name,
            "page_js": page.js_name,
            "show_shell": page.show_shell,
            "nav_items": build_nav_items(),
            "current_user": context.pop("current_user", None),
            **context,
        },
    )
