from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.core.config import get_settings
from app.modules.admin.service import AdminService, host_metrics, storage_usage
from app.modules.auth.dependencies import require_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def get_admin_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> AdminService:
    return AdminService(session, get_settings())


Service = Annotated[AdminService, Depends(get_admin_service)]


STATUS_PATTERN = "^(pending|processing|succeeded|failed|cancelled)$"


class RetryRequest(BaseModel):
    ids: list[str] | None = Field(default=None, max_length=1000)


class CountResponse(BaseModel):
    count: int


@router.get("/overview", summary="System overview for the owner dashboard")
async def overview(request: Request, service: Service) -> dict[str, Any]:
    storage = request.app.state.storage
    root = getattr(storage, "root", None)
    return {
        "config": service.config_summary(),
        "host": host_metrics(root),
        "database": await service.database(),
        "storage": await storage_usage(storage),
        "queues": await service.queues(),
        "workers": await service.workers(),
        "totals": await service.totals(),
    }


@router.get("/storage", summary="Storage usage (cached; refresh=true recomputes)")
async def storage(request: Request, refresh: bool = False) -> dict[str, Any]:
    return await storage_usage(request.app.state.storage, force=refresh)


@router.get("/queues/{queue}/jobs", summary="Jobs or event deliveries of one queue")
async def list_jobs(
    queue: str,
    service: Service,
    status: Annotated[str | None, Query(pattern=STATUS_PATTERN)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return await service.list_jobs(queue, status=status, limit=limit, offset=offset)


@router.post("/queues/{queue}/retry", summary="Re-queue failed jobs (all, or the given ids)")
async def retry_jobs(queue: str, body: RetryRequest, service: Service) -> CountResponse:
    return CountResponse(count=await service.retry_jobs(queue, ids=body.ids))


@router.delete("/queues/{queue}/failed", summary="Delete failed jobs (dead letters)")
async def purge_failed(queue: str, service: Service) -> CountResponse:
    return CountResponse(count=await service.purge_failed(queue))
