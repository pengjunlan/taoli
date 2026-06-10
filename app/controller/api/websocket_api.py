"""WebSocket routes."""

from fastapi import APIRouter, WebSocket

from app.controller.dependencies import enforce_websocket_auth


router = APIRouter()


@router.websocket("/ws/live/{channel}")
async def live_ws(websocket: WebSocket, channel: str) -> None:
    user = await enforce_websocket_auth(websocket)
    if user is None:
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "success": False,
            "channel": channel,
            "message": "当前版本不再提供原型 WebSocket 推送，请改用页面 AJAX 接口。",
        }
    )
    await websocket.close(code=1000)
