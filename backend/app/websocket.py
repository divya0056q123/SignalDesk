import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder


class EventHub:
    def __init__(self):
        self._clients: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, tenant_id: str = "default") -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.setdefault(tenant_id, set()).add(websocket)

    async def disconnect(self, websocket: WebSocket, tenant_id: str = "default") -> None:
        async with self._lock:
            clients = self._clients.get(tenant_id)
            if clients:
                clients.discard(websocket)
                if not clients:
                    self._clients.pop(tenant_id, None)

    async def broadcast(self, event: dict, tenant_id: str = "default") -> None:
        async with self._lock:
            clients = tuple(self._clients.get(tenant_id, ()))
        disconnected = []
        for client in clients:
            try:
                await client.send_json(jsonable_encoder(event))
            except (RuntimeError, OSError, WebSocketDisconnect):
                disconnected.append(client)
        for client in disconnected:
            await self.disconnect(client, tenant_id)
