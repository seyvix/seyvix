from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.recommendations.schemas import NoteRecommendationsResponse
from app.modules.recommendations.service import (
    MAX_NOTE_RECOMMENDATIONS,
    RecommendationNoteNotFoundError,
    RecommendationService,
)

router = APIRouter(prefix="/notes", tags=["recommendations"])


def get_recommendation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RecommendationService:
    return RecommendationService(session)


@router.get(
    "/{note_ref}/recommendations",
    response_model=NoteRecommendationsResponse,
    summary="Recommend semantically similar notes",
    description=(
        "Returns up to five semantically similar notes from the current user's indexed content "
        "database. The current note and deleted notes are excluded."
    ),
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def recommend_notes(
    note_ref: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
    limit: Annotated[
        int,
        Query(
            ge=1,
            description="Requested number of recommendations. Values above five are capped.",
        ),
    ] = MAX_NOTE_RECOMMENDATIONS,
) -> NoteRecommendationsResponse:
    try:
        return await service.recommend_notes(
            owner_user_id=context.user.id,
            note_ref=note_ref,
            limit=limit,
        )
    except RecommendationNoteNotFoundError as exc:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="note_not_found",
            message="Note not found.",
        ) from exc
