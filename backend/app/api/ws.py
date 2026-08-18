"""WebSocket: live AI activity stream for the dashboard log console."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.logging import subscribe, unsubscribe

router = APIRouter()


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    queue = subscribe()
    try:
        while True:
            entry = await queue.get()
            await websocket.send_json(entry)
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(queue)
