"""API route aggregation entrypoint."""

from fastapi import APIRouter

from app.controller.api.account_api import router as account_router
from app.controller.api.auth_api import router as auth_router
from app.controller.api.dashboard_api import router as dashboard_router
from app.controller.api.opportunity_diagnostics_api import router as opportunity_diagnostics_router
from app.controller.api.opportunity_api import router as opportunity_router
from app.controller.api.risk_api import router as risk_router
from app.controller.api.strategy_api import router as strategy_router
from app.controller.api.system_exchange_api import router as system_exchange_router
from app.controller.api.websocket_api import router as websocket_router

router = APIRouter()

router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(opportunity_router)
router.include_router(opportunity_diagnostics_router)
router.include_router(account_router)
router.include_router(risk_router)
router.include_router(strategy_router)
router.include_router(system_exchange_router)
router.include_router(websocket_router)
