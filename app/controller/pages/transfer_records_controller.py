from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.controller.dependencies import get_optional_current_user
from app.views.presenters.page_presenters.template_renderer import render_page
from app.views.viewmodels.page_models import PageConfig
from app.views.viewmodels.pages.page_contexts import transfer_records_context_for_user


router = APIRouter()

PAGE = PageConfig(
    key="transfer_records",
    template_name="pages/transfer_records.html",
    title="调拨记录",
    subtitle="统一查看账户调拨任务的执行状态、触发原因和到账结果。",
    css_name="transfer_records.css",
    js_name="transfer_records.js",
)


@router.get("/transfer-records", response_class=HTMLResponse)
async def transfer_records_page(request: Request) -> HTMLResponse:
    current_user = get_optional_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    return render_page(request, PAGE, current_user=current_user, **transfer_records_context_for_user(current_user.id))
