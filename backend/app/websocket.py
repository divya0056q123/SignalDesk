import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder


class EventHub:
    def __init__(self):
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, event: dict) -> None:
        async with self._lock:
            clients = tuple(self._clients)
        disconnected = []
        for client in clients:
            try:
                await client.send_json(jsonable_encoder(event))
            except (RuntimeError, OSError, WebSocketDisconnect):
                disconnected.append(client)
        for client in disconnected:
            await self.disconnect(client)
