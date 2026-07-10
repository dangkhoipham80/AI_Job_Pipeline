"""WebSocket hub for realtime dashboard updates.

Phase 2 provides the plumbing: a connection manager + ``/ws`` endpoint that
authenticates via ``?token=`` and echoes messages. Later phases call
``manager.broadcast(...)`` to push crawl/tailor/apply progress.
"""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from jobpilot import __version__
from jobpilot.config import get_secrets


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        for ws in list(self.active):
            try:
                if ws.application_state == WebSocketState.CONNECTED:
                    await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


async def websocket_endpoint(ws: WebSocket) -> None:
    token = ws.query_params.get("token")
    expected = get_secrets().jobpilot_api_token
    if not expected or token != expected:
        await ws.close(code=1008)  # policy violation
        return

    await manager.connect(ws)
    try:
        await ws.send_json({"type": "hello", "version": __version__})
        while True:
            data = await ws.receive_text()
            await ws.send_json({"type": "echo", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
        raise
