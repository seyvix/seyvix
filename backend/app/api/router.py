from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.schemas import HealthResponse
from app.modules.admin.router import router as admin_router
from app.modules.auth.presentation.rest.admin_router import router as admin_access_router
from app.modules.auth.presentation.rest.router import router as auth_router
from app.modules.content.presentation.rest.router import router as content_router
from app.modules.recommendations.presentation.rest.router import router as recommendations_router
from app.modules.search.presentation.rest.router import router as search_router
from app.modules.snapshots.presentation.rest.router import router as snapshots_router
from app.modules.tags.presentation.rest.router import router as tags_router
from app.modules.taxonomy.presentation.rest.router import router as taxonomy_router
from app.modules.telegram_integration.presentation.rest.router import router as telegram_router
from app.modules.vectorization.presentation.rest.router import router as vectorization_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(admin_access_router)
api_router.include_router(content_router)
api_router.include_router(recommendations_router)
api_router.include_router(snapshots_router)
api_router.include_router(taxonomy_router)
api_router.include_router(tags_router)
api_router.include_router(vectorization_router)
api_router.include_router(search_router)
api_router.include_router(telegram_router)
api_router.include_router(admin_router)


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
    description="Checks PostgreSQL connectivity and that the storage backend is reachable.",
)
async def readiness(request: Request) -> JSONResponse:
    checks: dict[str, bool] = {}
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("select 1"))
        checks["postgresql"] = True
    except Exception:  # noqa: BLE001
        checks["postgresql"] = False
    try:
        checks["storage"] = await request.app.state.storage.is_ready()
    except Exception:  # noqa: BLE001
        checks["storage"] = False
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ok" if ready else "not_ready", "checks": checks},
        status_code=200 if ready else 503,
    )
