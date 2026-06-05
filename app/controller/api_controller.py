import asyncio
from typing import Callable, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.service.prototype_data import (
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


@router.get("/api/dashboard")
async def dashboard_api() -> Dict[str, object]:
    return build_dashboard_payload()


@router.get("/api/funding-opportunities")
async def funding_api() -> Dict[str, object]:
    return build_funding_payload()


@router.get("/api/spread-opportunities")
async def spread_api() -> Dict[str, object]:
    return build_spread_payload()


@router.websocket("/ws/live/{channel}")
async def live_ws(websocket: WebSocket, channel: str) -> None:
    builder = PAYLOAD_BUILDERS.get(channel)
    if builder is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    try:
        while True:
            await websocket.send_json(builder())
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
