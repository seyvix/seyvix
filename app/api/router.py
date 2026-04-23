from fastapi import APIRouter

from app.modules.registry import list_modules

api_router = APIRouter()


@api_router.get("/health", tags=["system"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@api_router.get("/modules", tags=["system"])
async def modules_overview() -> list[dict[str, object]]:
    return [module.model_dump(mode="json") for module in list_modules()]
