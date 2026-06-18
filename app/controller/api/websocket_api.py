"""WebSocket routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.application.services.live_push_service import live_push_service
from app.controller.dependencies import enforce_websocket_auth


router = APIRouter()
logger = logging.getLogger(__name__)

SUPPORTED_CHANNELS = {
    "accounts",
    "funding",
    "spread",
    "strategy-runtime",
}


@router.websocket("/ws/live/{channel}")
async def live_ws(websocket: WebSocket, channel: str) -> None:
    user = await enforce_websocket_auth(websocket)
    if user is None:
        return

    normalized_channel = str(channel or "").strip().lower()
    raw_page = websocket.query_params.get("page", "1")
    raw_page_size = websocket.query_params.get("page_size", "5")
    raw_keys = websocket.query_params.get("keys", "")
    await websocket.accept()

    if normalized_channel not in SUPPORTED_CHANNELS:
        await websocket.send_json(
            {
                "success": False,
                "channel": normalized_channel,
                "message": "unsupported_channel",
            }
        )
        await websocket.close(code=1003)
        return

    try:
        page = max(1, int(raw_page or 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = max(1, min(20, int(raw_page_size or 5)))
    except (TypeError, ValueError):
        page_size = 5

    locked_keys = [
        item.strip()
        for item in str(raw_keys or "").split(",")
        if str(item or "").strip()
    ]

    try:
        while True:
            payload = live_push_service.build_payload(
                channel=normalized_channel,
                user_id=user.id,
                page=page,
                page_size=page_size,
                locked_keys=locked_keys,
            )
            await websocket.send_json(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.debug(
            "Live websocket disconnected: user_id=%s channel=%s",
            user.id,
            normalized_channel,
        )
    except RuntimeError:
        logger.debug(
            "Live websocket closed while sending: user_id=%s channel=%s",
            user.id,
            normalized_channel,
        )
    except Exception:
        logger.exception(
            "Live websocket push failed: user_id=%s channel=%s",
            user.id,
            normalized_channel,
        )
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass
