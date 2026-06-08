"""WebSocket routes for prototype live feeds."""

import asyncio
from typing import Callable, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.controller.dependencies import enforce_websocket_auth
from app.views.presenters.api_presenters.prototype_payloads import (
    build_dashboard_payload,
    build_funding_payload,
    build_spread_payload,
)


router = APIRouter()

PAYLOAD_BUILDERS: Dict[str, Callable[[], Dict[str, object]]] = {
    "dashboard": build_dashboard_payload,
    "funding": build_funding_payload,
    "spread": build_spread_payload,
}


@router.websocket("/ws/live/{channel}")
async def live_ws(websocket: WebSocket, channel: str) -> None:
    builder = PAYLOAD_BUILDERS.get(channel)
    if builder is None:
        await websocket.close(code=1008)
        return

    user = await enforce_websocket_auth(websocket)
    if user is None:
        return

    await websocket.accept()

    try:
        while True:
            await websocket.send_json(builder())
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
