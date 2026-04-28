from fastapi import APIRouter

from app.api.schemas import HealthResponse
from app.modules.auth.presentation.rest.router import router as auth_router
from app.modules.content.presentation.rest.router import router as content_router
from app.modules.registry import list_modules
from app.modules.snapshots.presentation.rest.router import router as snapshots_router
from app.shared.module_definitions import ModuleDefinition

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(content_router)
api_router.include_router(snapshots_router)


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
    "/modules",
    tags=["system"],
    response_model=list[ModuleDefinition],
    summary="List modules",
    description="Returns registered bounded modules and their public contracts.",
)
async def modules_overview() -> list[ModuleDefinition]:
    return list(list_modules())
