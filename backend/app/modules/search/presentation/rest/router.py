from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.core.config import get_settings
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.content.infrastructure.repositories import ContentRepository
from app.modules.search.infrastructure.meilisearch import MeilisearchUnavailableError
from app.modules.search.schemas import (
    HybridSearchRequest,
    HybridSearchResponse,
    SearchCapabilitiesResponse,
    SearchMode,
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from app.modules.search.service import SearchValidationError, SemanticSearchService

router = APIRouter(prefix="/search", tags=["search"])


def get_semantic_search_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SemanticSearchService:
    return SemanticSearchService(session)


@router.post(
    "/semantic",
    response_model=SemanticSearchResponse,
    summary="Search indexed vectorized chunks semantically",
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def semantic_search(
    payload: SemanticSearchRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
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
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            message="Search query must not be empty.",
        ) from exc
    except (ValueError, MeilisearchUnavailableError) as exc:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="semantic_search_unavailable",
            message="Semantic search embedding provider is not available.",
        ) from exc
    return SemanticSearchResponse(query=payload.query.strip(), results=results)


@router.post(
    "/hybrid",
    response_model=HybridSearchResponse,
    summary="Search indexed chunks with full-text, semantic vectors, and RRF ranking",
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def hybrid_search(
    payload: HybridSearchRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SemanticSearchService, Depends(get_semantic_search_service)],
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
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            message="Search query must not be empty.",
        ) from exc
    except (ValueError, MeilisearchUnavailableError) as exc:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="hybrid_search_unavailable",
            message="Hybrid search provider is not available.",
        ) from exc


@router.get(
    "/capabilities",
    response_model=SearchCapabilitiesResponse,
    summary="Search capabilities for the current user",
    description=(
        "Returns the user's note count, the minimum threshold for vector "
        "search modes, the list of currently unlocked modes, and the "
        "recommended default mode."
    ),
)
async def get_search_capabilities(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SearchCapabilitiesResponse:
    settings = get_settings()
    repo = ContentRepository(session)
    note_count = await repo.count_owned_notes(owner_user_id=context.user.id)

    meilisearch_available = (
        settings.search_engine == "meilisearch"
        and bool(settings.search_meilisearch_url)
    )
    vector_modes_unlocked = (
        meilisearch_available
        and note_count >= settings.search_vector_modes_min_notes
    )

    unlocked: list[SearchMode] = ["full_text"]
    if vector_modes_unlocked:
        unlocked.extend(["semantic", "hybrid"])

    default_mode: SearchMode = "hybrid" if vector_modes_unlocked else "full_text"

    return SearchCapabilitiesResponse(
        note_count=note_count,
        threshold=settings.search_vector_modes_min_notes,
        unlocked_modes=unlocked,
        default_mode=default_mode,
    )
