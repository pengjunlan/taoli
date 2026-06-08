from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.controller.pages.accounts_controller import router as accounts_router
from app.controller.pages.dashboard_controller import router as dashboard_router
from app.controller.pages.funding_arbitrage_controller import router as funding_arbitrage_router
from app.controller.pages.login_controller import router as login_router
from app.controller.pages.positions_orders_controller import router as positions_orders_router
from app.controller.pages.register_controller import router as register_router
from app.controller.pages.risk_alerts_controller import router as risk_alerts_router
from app.controller.pages.spread_arbitrage_controller import router as spread_arbitrage_router
from app.controller.pages.strategy_list_controller import router as strategy_list_router
from app.controller.pages.transfer_records_controller import router as transfer_records_router


router = APIRouter()


@router.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)


router.include_router(login_router)
router.include_router(register_router)
router.include_router(dashboard_router)
router.include_router(funding_arbitrage_router)
router.include_router(spread_arbitrage_router)
router.include_router(strategy_list_router)
router.include_router(positions_orders_router)
router.include_router(accounts_router)
router.include_router(transfer_records_router)
router.include_router(risk_alerts_router)
