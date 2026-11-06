from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.search.schemas import (
    HybridSearchRequest,
    HybridSearchResponse,
    SearchCapabilitiesResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from app.modules.search.service import (
    SearchService,
    SearchUnavailableError,
    SearchValidationError,
)

router = APIRouter(prefix="/search", tags=["search"])


def get_search_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SearchService:
    return SearchService(session)


def _empty_query_error(exc: SearchValidationError) -> AppError:
    return AppError(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        message=str(exc) or "Search query must not be empty.",
    )


@router.post(
    "/semantic",
    response_model=SemanticSearchResponse,
    summary="Search indexed chunks by embedding similarity (requires AI)",
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def semantic_search(
    payload: SemanticSearchRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SearchService, Depends(get_search_service)],
) -> SemanticSearchResponse:
    try:
        results = await service.semantic_search(
            owner_user_id=context.user.id,
            query=payload.query,
            limit=payload.limit,
            source=payload.source,
            source_type=payload.source_type,
            source_id=payload.source_id,
            filters=payload.filters,
        )
    except SearchValidationError as exc:
        raise _empty_query_error(exc) from exc
    except SearchUnavailableError as exc:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="semantic_search_unavailable",
            message="Semantic search is not available (AI disabled or unreachable).",
        ) from exc
    return SemanticSearchResponse(query=" ".join(payload.query.split()), results=results)


@router.post(
    "/hybrid",
    response_model=HybridSearchResponse,
    summary="Search indexed chunks with full-text and (when AI is available) vectors, RRF-fused",
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def hybrid_search(
    payload: HybridSearchRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SearchService, Depends(get_search_service)],
) -> HybridSearchResponse:
    try:
        return await service.hybrid_search(
            owner_user_id=context.user.id,
            query=payload.query,
            limit=payload.limit,
            source=payload.source,
            source_type=payload.source_type,
            source_id=payload.source_id,
            filters=payload.filters,
            expand_query=payload.expand_query,
            mode=payload.mode,
        )
    except SearchValidationError as exc:
        raise _empty_query_error(exc) from exc


@router.get(
    "/capabilities",
    response_model=SearchCapabilitiesResponse,
    summary="Search capabilities for the current user",
    description=(
        "Returns the user's note count, the minimum note count for vector modes (0), the "
        "currently unlocked modes, the recommended default mode and whether AI is enabled. "
        "Without AI only full_text is unlocked."
    ),
)
async def get_search_capabilities(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SearchService, Depends(get_search_service)],
) -> SearchCapabilitiesResponse:
    return await service.capabilities(owner_user_id=context.user.id)
