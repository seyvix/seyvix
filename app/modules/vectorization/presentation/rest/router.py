from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.vectorization.schemas import (
    VectorizationChunkResponse,
    VectorizationIndexRequestBody,
    VectorizationIndexResponse,
    VectorizationJobResponse,
    VectorizationSourceResponse,
)
from app.modules.vectorization.service import (
    VectorizationProviderNotFoundError,
    VectorizationService,
)

router = APIRouter(prefix="/vectorization", tags=["vectorization"])


def get_vectorization_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VectorizationService:
    return VectorizationService(session)


@router.post(
    "/index",
    response_model=VectorizationIndexResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue vectorization indexing for a source",
    responses={
        202: {"description": "Indexing job enqueued."},
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def enqueue_index(
    payload: VectorizationIndexRequestBody,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[VectorizationService, Depends(get_vectorization_service)],
) -> VectorizationIndexResponse:
    try:
        job = await service.enqueue_index_request(
            owner_user_id=context.user.id,
            source=payload.source,
            source_type=payload.source_type,
            source_id=payload.source_id,
            priority=payload.priority,
            reason=payload.reason,
        )
    except VectorizationProviderNotFoundError as exc:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="vectorization_provider_not_found",
            message="Vectorization provider not found for requested source.",
        ) from exc
    return VectorizationIndexResponse(job_id=job.id, status=job.status)


@router.get(
    "/jobs",
    response_model=list[VectorizationJobResponse],
    summary="List vectorization jobs for the current user",
    responses={401: {"model": ErrorResponse}},
)
async def list_jobs(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[VectorizationService, Depends(get_vectorization_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[VectorizationJobResponse]:
    return [
        VectorizationJobResponse.model_validate(job)
        for job in await service.repository.list_jobs(owner_user_id=context.user.id, limit=limit)
    ]


@router.get(
    "/sources",
    response_model=list[VectorizationSourceResponse],
    summary="List vectorization sources for the current user",
    responses={401: {"model": ErrorResponse}},
)
async def list_sources(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[VectorizationService, Depends(get_vectorization_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[VectorizationSourceResponse]:
    return [
        VectorizationSourceResponse.model_validate(source)
        for source in await service.repository.list_sources(
            owner_user_id=context.user.id,
            limit=limit,
        )
    ]


@router.get(
    "/chunks",
    response_model=list[VectorizationChunkResponse],
    summary="List vectorization chunks for the current user",
    responses={401: {"model": ErrorResponse}},
)
async def list_chunks(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[VectorizationService, Depends(get_vectorization_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[VectorizationChunkResponse]:
    return [
        VectorizationChunkResponse.model_validate(chunk)
        for chunk in await service.repository.list_chunks(
            owner_user_id=context.user.id, limit=limit
        )
    ]
