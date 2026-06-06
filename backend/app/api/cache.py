from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.responses import Response

API_NO_STORE = "private, no-store, max-age=0"
PUBLIC_HEALTH_CACHE = "public, max-age=5, stale-while-revalidate=30"
PRIVATE_FILE_CACHE = "private, max-age=86400, stale-while-revalidate=604800"


def install_cache_control(app: FastAPI, *, api_prefix: str) -> None:
    @app.middleware("http")
    async def cache_control_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if "Cache-Control" in response.headers:
            return response

        policy = _cache_policy(
            path=request.url.path,
            method=request.method,
            status_code=response.status_code,
            api_prefix=api_prefix,
        )
        if policy is None:
            return response

        response.headers["Cache-Control"] = policy
        if policy.startswith("private") and response.status_code == 200:
            _append_vary(response, "Authorization", "Cookie")
        if "no-store" in policy:
            response.headers.setdefault("Pragma", "no-cache")
        return response


def _cache_policy(*, path: str, method: str, status_code: int, api_prefix: str) -> str | None:
    if path in {
        f"{api_prefix}/health",
        f"{api_prefix}/health/live",
        f"{api_prefix}/health/ready",
    }:
        return PUBLIC_HEALTH_CACHE

    if not path.startswith(api_prefix):
        return None

    if method.upper() not in {"GET", "HEAD"}:
        return API_NO_STORE

    if status_code == 200 and _is_cacheable_private_file(path=path, api_prefix=api_prefix):
        return PRIVATE_FILE_CACHE

    return API_NO_STORE


def _is_cacheable_private_file(*, path: str, api_prefix: str) -> bool:
    return (
        path.startswith(f"{api_prefix}/snapshots/artifacts/")
        or (
            path.startswith(f"{api_prefix}/notes/")
            and "/asset/" in path
        )
    )


def _append_vary(response: Response, *values: str) -> None:
    existing = response.headers.get("Vary")
    seen = {
        item.strip().lower()
        for item in (existing or "").split(",")
        if item.strip()
    }
    merged = [item.strip() for item in (existing or "").split(",") if item.strip()]

    for value in values:
        if value.lower() not in seen:
            merged.append(value)
            seen.add(value.lower())

    if merged:
        response.headers["Vary"] = ", ".join(merged)
