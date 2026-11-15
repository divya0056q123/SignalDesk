import json

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, limits: dict[str, int]):
        self.app = app
        self.limits = limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in self.limits:
            await self.app(scope, receive, send)
            return

        limit = self.limits[scope["path"]]
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    response = JSONResponse(
                        {"detail": f"Request body exceeds the {limit}-byte limit"},
                        status_code=413,
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0
        oversized = False
        response_body = json.dumps({"detail": f"Request body exceeds the {limit}-byte limit"}).encode()

        async def limited_receive():
            nonlocal received, oversized
            message = await receive()
            if message["type"] == "http.request" and not oversized:
                received += len(message.get("body", b""))
                if received > limit:
                    oversized = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def limited_send(message):
            if not oversized:
                await send(message)
            elif message["type"] == "http.response.start":
                await send({
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(response_body)).encode()),
                    ],
                })
            elif message["type"] == "http.response.body":
                await send({**message, "body": response_body, "more_body": False})

        await self.app(scope, limited_receive, limited_send)
