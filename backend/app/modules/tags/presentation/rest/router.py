from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.tags.models import ContentTagAssignment, Tag, TaggingJob
from app.modules.tags.schemas import (
    ContentTagAssignmentResponse,
    ContentTagDryRunResponse,
    ContentTagSuggestionResponse,
    ManualAssignTagRequest,
    SuggestContentTagsRequest,
    TagCreateRequest,
    TaggingJobDetailResponse,
    TaggingJobListResponse,
    TaggingJobResponse,
    TagMergeRequest,
    TagResponse,
    TagReviewQueueResponse,
    TagsJobMetricsResponse,
    TagUpdateRequest,
)
from app.modules.tags.service import (
    TagConflictError,
    TagLLMDisabledError,
    TagNotFoundError,
    TagsService,
    TagValidationError,
)

router = APIRouter(tags=["tags"])


def get_tags_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TagsService:
    return TagsService(session)


def _tag_response(tag: Tag) -> TagResponse:
    return TagResponse(
        id=tag.id,
        name=tag.name,
        slug=tag.slug,
        description=tag.description,
        tag_kind=tag.tag_kind,
        aliases=tag.aliases,
        created_by_type=tag.created_by_type,  # type: ignore[arg-type]
        created_by_user_id=tag.created_by_user_id,
        source=tag.source,  # type: ignore[arg-type]
        source_detail=tag.source_detail,
        confidence=tag.confidence,
        is_archived=tag.is_archived,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )


def _assignment_response(assignment: ContentTagAssignment) -> ContentTagAssignmentResponse:
    return ContentTagAssignmentResponse(
        id=assignment.id,
        content_object_id=assignment.content_object_id,
        tag=_tag_response(assignment.tag),
        status=assignment.status,  # type: ignore[arg-type]
        assigned_by_type=assignment.assigned_by_type,  # type: ignore[arg-type]
        assigned_by_user_id=assignment.assigned_by_user_id,
        source=assignment.source,  # type: ignore[arg-type]
        source_detail=assignment.source_detail,
        confidence=assignment.confidence,
        reasoning=assignment.reasoning,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _job_response(job: TaggingJob) -> TaggingJobDetailResponse:
    return TaggingJobDetailResponse(
        id=job.id,
        content_object_id=job.content_object_id,
        job_type=job.job_type,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        source_event_id=job.source_event_id,
        correlation_id=job.correlation_id,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _raise_not_found(exc: Exception) -> AppError:
    return AppError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="tag_not_found",
        message="Tag or content object not found.",
    )


@router.post(
    "/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create tag",
    description="Creates an owner-scoped first-class tag with manual provenance.",
    responses={
        201: {"description": "Tag created."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        409: {"model": ErrorResponse, "description": "Tag slug already exists."},
    },
)
async def create_tag(
    payload: TagCreateRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> TagResponse:
    try:
        tag = await service.create_tag(
            owner_user_id=context.user.id,
            name=payload.name,
            description=payload.description,
            tag_kind=payload.tag_kind,
            aliases=payload.aliases,
            created_by_user_id=context.user.id,
        )
        return _tag_response(tag)
    except TagConflictError as exc:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="tag_duplicate_slug",
            message="Tag slug already exists.",
        ) from exc
    except TagValidationError as exc:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="tag_validation_error",
            message=str(exc),
        ) from exc


@router.get(
    "/tags",
    response_model=list[TagResponse],
    summary="List tags",
    description="Returns owner-scoped tags. Archived tags are hidden by default.",
)
async def list_tags(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
    include_archived: Annotated[bool, Query()] = False,
) -> list[TagResponse]:
    tags = await service.list_tags(
        owner_user_id=context.user.id,
        include_archived=include_archived,
    )
    return [_tag_response(tag) for tag in tags]


@router.get("/tags/{tag_id}", response_model=TagResponse, summary="Get tag")
async def get_tag(
    tag_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> TagResponse:
    try:
        tag = await service._get_tag(owner_user_id=context.user.id, tag_id=tag_id)
        return _tag_response(tag)
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc


@router.patch("/tags/{tag_id}", response_model=TagResponse, summary="Update tag")
async def update_tag(
    tag_id: str,
    payload: TagUpdateRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> TagResponse:
    try:
        tag = await service.update_tag(
            owner_user_id=context.user.id,
            tag_id=tag_id,
            name=payload.name,
            description=payload.description,
            tag_kind=payload.tag_kind,
            aliases=payload.aliases,
            is_archived=payload.is_archived,
        )
        return _tag_response(tag)
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc
    except TagConflictError as exc:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="tag_duplicate_slug",
            message="Tag slug already exists.",
        ) from exc


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Archive tag")
async def archive_tag(
    tag_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> Response:
    try:
        await service.archive_tag(owner_user_id=context.user.id, tag_id=tag_id)
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tags/{tag_id}/merge", response_model=TagResponse, summary="Merge tag")
async def merge_tag(
    tag_id: str,
    payload: TagMergeRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> TagResponse:
    try:
        tag = await service.merge_tags(
            owner_user_id=context.user.id,
            source_tag_id=tag_id,
            target_tag_id=payload.target_tag_id,
            assigned_by_user_id=context.user.id,
        )
        return _tag_response(tag)
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc
    except TagConflictError as exc:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="tag_merge_conflict",
            message="Tags cannot be merged.",
        ) from exc


@router.get(
    "/tag-suggestions/review-queue",
    response_model=TagReviewQueueResponse,
    summary="List pending tag suggestions",
)
async def list_tag_review_queue(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TagReviewQueueResponse:
    assignments = await service.list_review_suggestions(
        owner_user_id=context.user.id,
        limit=limit,
        offset=offset,
    )
    return TagReviewQueueResponse(items=[_assignment_response(item) for item in assignments])


@router.get(
    "/tag-jobs/metrics",
    response_model=TagsJobMetricsResponse,
    summary="Get tag job metrics",
)
async def tag_job_metrics(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> TagsJobMetricsResponse:
    return await service.job_metrics(owner_user_id=context.user.id)


@router.post(
    "/content/{content_object_id}/tags",
    response_model=ContentTagAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign tag to content object",
)
async def assign_tag(
    content_object_id: str,
    payload: ManualAssignTagRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> ContentTagAssignmentResponse:
    try:
        existing = await service.repository.get_active_assignment(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            tag_id=payload.tag_id,
        )
        assignment = await service.assign_tag_to_content(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            tag_id=payload.tag_id,
            assigned_by_user_id=context.user.id,
            reasoning=payload.reasoning,
        )
        if existing is not None:
            response.status_code = status.HTTP_200_OK
        return _assignment_response(assignment)
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc
    except TagConflictError as exc:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="tag_assignment_conflict",
            message="Tag cannot be assigned to this content object.",
        ) from exc


@router.get(
    "/content/{content_object_id}/tags",
    response_model=list[ContentTagAssignmentResponse],
    summary="List content tag assignments",
)
async def list_content_tags(
    content_object_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> list[ContentTagAssignmentResponse]:
    try:
        assignments = await service.list_tags_for_content(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            statuses={"accepted"},
        )
        return [_assignment_response(assignment) for assignment in assignments]
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc


@router.get(
    "/content/{content_object_id}/tags/jobs",
    response_model=TaggingJobListResponse,
    summary="List content tag suggestion jobs",
)
async def list_content_tag_jobs(
    content_object_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> TaggingJobListResponse:
    try:
        jobs = await service.list_jobs_for_content(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
        )
        return TaggingJobListResponse(items=[_job_response(job) for job in jobs])
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc


@router.delete(
    "/content/{content_object_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove content tag assignment",
)
async def remove_content_tag(
    content_object_id: str,
    tag_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> Response:
    try:
        await service.remove_tag_from_content(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            tag_id=tag_id,
            assigned_by_user_id=context.user.id,
        )
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/content/{content_object_id}/tags/suggest",
    response_model=TaggingJobResponse | ContentTagDryRunResponse,
    summary="Suggest content tags",
)
async def suggest_content_tags(
    content_object_id: str,
    payload: SuggestContentTagsRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> TaggingJobResponse | ContentTagDryRunResponse:
    try:
        if payload.dry_run:
            suggestions = await service.suggest_tags_for_content(
                owner_user_id=context.user.id,
                content_object_id=content_object_id,
                max_tags=payload.max_tags,
                persist=False,
            )
            return ContentTagDryRunResponse(
                content_object_id=content_object_id,
                suggestions=[
                    ContentTagSuggestionResponse(
                        name=suggestion.name,
                        slug=suggestion.slug,
                        confidence=suggestion.confidence,
                        reasoning=suggestion.reasoning,
                    )
                    for suggestion in suggestions
                ],
            )
        job = await service.enqueue_content_tag_suggestions(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
        )
        await service.session.commit()
        return TaggingJobResponse(job_id=job.id, status=job.status)
    except TagLLMDisabledError as exc:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="tags_llm_disabled",
            message="LLM tag suggestions are disabled.",
        ) from exc
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc


@router.get(
    "/content/{content_object_id}/tags/suggestions",
    response_model=list[ContentTagAssignmentResponse],
    summary="List pending content tag suggestions",
)
async def list_suggestions(
    content_object_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> list[ContentTagAssignmentResponse]:
    try:
        assignments = await service.list_tags_for_content(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            statuses={"suggested"},
        )
        return [_assignment_response(assignment) for assignment in assignments]
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc


@router.post(
    "/content/{content_object_id}/tags/suggestions/{assignment_id}/accept",
    response_model=ContentTagAssignmentResponse,
    summary="Accept tag suggestion",
)
async def accept_suggestion(
    content_object_id: str,
    assignment_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> ContentTagAssignmentResponse:
    try:
        assignment = await service.accept_suggestion(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
            assigned_by_user_id=context.user.id,
        )
        return _assignment_response(assignment)
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc
    except TagConflictError as exc:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="tag_suggestion_conflict",
            message="Tag suggestion cannot be accepted.",
        ) from exc


@router.post(
    "/content/{content_object_id}/tags/suggestions/{assignment_id}/reject",
    response_model=ContentTagAssignmentResponse,
    summary="Reject tag suggestion",
)
async def reject_suggestion(
    content_object_id: str,
    assignment_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TagsService, Depends(get_tags_service)],
) -> ContentTagAssignmentResponse:
    try:
        assignment = await service.reject_suggestion(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
            assigned_by_user_id=context.user.id,
        )
        return _assignment_response(assignment)
    except TagNotFoundError as exc:
        raise _raise_not_found(exc) from exc
    except TagConflictError as exc:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="tag_suggestion_conflict",
            message="Tag suggestion cannot be rejected.",
        ) from exc
