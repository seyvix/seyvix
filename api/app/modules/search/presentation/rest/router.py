from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.search.schemas import SemanticSearchRequest, SemanticSearchResponse
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
        )
    except SearchValidationError as exc:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            message="Search query must not be empty.",
        ) from exc
    except ValueError as exc:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="semantic_search_unavailable",
            message="Semantic search embedding provider is not available.",
        ) from exc
    return SemanticSearchResponse(query=payload.query.strip(), results=results)
