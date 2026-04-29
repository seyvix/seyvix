import inspect

import aio_pika
from fastapi import APIRouter, Request
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.schemas import HealthResponse
from app.core.config import get_settings
from app.modules.auth.presentation.rest.router import router as auth_router
from app.modules.content.presentation.rest.router import router as content_router
from app.modules.registry import list_modules
from app.modules.snapshots.presentation.rest.router import router as snapshots_router
from app.modules.taxonomy.presentation.rest.router import router as taxonomy_router
from app.shared.module_definitions import ModuleDefinition

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(content_router)
api_router.include_router(snapshots_router)
api_router.include_router(taxonomy_router)


@api_router.get(
    "/health",
    tags=["system"],
    response_model=HealthResponse,
    summary="Healthcheck",
    description="Simple liveness probe for local development and external health monitors.",
)
async def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok")


@api_router.get(
    "/health/live",
    tags=["system"],
    response_model=HealthResponse,
    summary="Liveness check",
    description="Returns ok when the API process is alive.",
)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@api_router.get(
    "/health/ready",
    tags=["system"],
    summary="Readiness check",
    description="Checks PostgreSQL, Redis, RabbitMQ, and configured object storage.",
)
async def readiness(request: Request) -> dict[str, object]:
    settings = get_settings()
    checks: dict[str, bool] = {}

    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("select 1"))
        checks["postgresql"] = True
    except Exception:
        checks["postgresql"] = False

    redis = Redis.from_url(settings.redis_url)
    try:
        ping_response = redis.ping()
        if inspect.isawaitable(ping_response):
            ping_response = await ping_response
        checks["redis"] = bool(ping_response)
    except Exception:
        checks["redis"] = False
    finally:
        await redis.aclose()

    try:
        connection = await aio_pika.connect_robust(settings.rabbitmq_url, timeout=2)
        await connection.close()
        checks["rabbitmq"] = True
    except Exception:
        checks["rabbitmq"] = False

    try:
        backend = getattr(request.app.state, "storage_backend", None)
        if backend is None:
            checks["storage"] = True
        elif hasattr(backend, "client"):
            import asyncio

            checks["storage"] = await asyncio.to_thread(
                backend.client.bucket_exists,
                backend.bucket,
            )
        else:
            checks["storage"] = True
    except Exception:
        checks["storage"] = False

    return {"status": "ok" if all(checks.values()) else "not_ready", "checks": checks}


@api_router.get(
    "/modules",
    tags=["system"],
    response_model=list[ModuleDefinition],
    summary="List modules",
    description="Returns registered bounded modules and their public contracts.",
)
async def modules_overview() -> list[ModuleDefinition]:
    return list(list_modules())
