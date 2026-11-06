"""Default `Cache-Control` for API responses (pure ASGI: no body buffering, streams intact).

Routes that set their own `Cache-Control` (file endpoints) are left untouched; everything else
under the API prefix is `no-store`, health probes get a short public cache.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_NO_STORE = "private, no-store, max-age=0"
PUBLIC_HEALTH_CACHE = "public, max-age=5, stale-while-revalidate=30"


class CacheControlMiddleware:
    def __init__(self, app: ASGIApp, *, api_prefix: str) -> None:
        self.app = app
        self.api_prefix = api_prefix
        self.health_paths = {
            f"{api_prefix}/health",
            f"{api_prefix}/health/live",
            f"{api_prefix}/health/ready",
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        if path in self.health_paths:
            policy = PUBLIC_HEALTH_CACHE
        elif path.startswith(self.api_prefix):
            policy = API_NO_STORE
        else:
            await self.app(scope, receive, send)
            return

        async def send_with_cache_control(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "cache-control" not in headers:
                    headers["Cache-Control"] = policy
                    if policy == API_NO_STORE:
                        headers.setdefault("Pragma", "no-cache")
            await send(message)

        await self.app(scope, receive, send_with_cache_control)


def install_cache_control(app: FastAPI, *, api_prefix: str) -> None:
    app.add_middleware(CacheControlMiddleware, api_prefix=api_prefix)
