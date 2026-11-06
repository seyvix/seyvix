from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.llm.client import get_ai_client
from app.modules.tags.ai import ai_disabled_error, interactive_ai, tagging_enabled
from app.modules.tags.errors import (
    TagConflictError,
    TaggingDisabledError,
    TagNotFoundError,
    TagValidationError,
)
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
from app.modules.tags.service import TagsService
from app.modules.tags.suggestions import generate_suggestions, load_tagging_input

router = APIRouter(tags=["tags"])

AI_DISABLED_MESSAGE = "AI tag suggestions are disabled on this server."


def get_tags_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TagsService:
    return TagsService(session)


Auth = Annotated[AuthContext, Depends(get_auth_context)]
Service = Annotated[TagsService, Depends(get_tags_service)]


def _tag_response(tag: Tag) -> TagResponse:
    return TagResponse.model_validate(tag, from_attributes=True)


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
    return TaggingJobDetailResponse.model_validate(job, from_attributes=True)


def _not_found() -> AppError:
    return AppError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="tag_not_found",
        message="Tag or content object not found.",
    )


def _conflict(code: str, message: str) -> AppError:
    return AppError(status_code=status.HTTP_409_CONFLICT, code=code, message=message)


@router.post(
    "/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create tag",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        409: {"model": ErrorResponse, "description": "Tag slug already exists."},
    },
)
async def create_tag(payload: TagCreateRequest, context: Auth, service: Service) -> TagResponse:
    try:
        tag = await service.create_tag(
            owner_user_id=context.user.id,
            name=payload.name,
            description=payload.description,
            tag_kind=payload.tag_kind,
            aliases=payload.aliases,
            created_by_user_id=context.user.id,
        )
    except TagConflictError as exc:
        raise _conflict("tag_duplicate_slug", "Tag slug already exists.") from exc
    except TagValidationError as exc:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="tag_validation_error",
            message=str(exc),
        ) from exc
    return _tag_response(tag)


@router.get("/tags", response_model=list[TagResponse], summary="List tags")
async def list_tags(
    context: Auth,
    service: Service,
    include_archived: Annotated[bool, Query()] = False,
) -> list[TagResponse]:
    tags = await service.list_tags(owner_user_id=context.user.id, include_archived=include_archived)
    return [_tag_response(tag) for tag in tags]


@router.get("/tags/{tag_id}", response_model=TagResponse, summary="Get tag")
async def get_tag(tag_id: str, context: Auth, service: Service) -> TagResponse:
    try:
        return _tag_response(await service.get_tag(owner_user_id=context.user.id, tag_id=tag_id))
    except TagNotFoundError as exc:
        raise _not_found() from exc


@router.patch("/tags/{tag_id}", response_model=TagResponse, summary="Update tag")
async def update_tag(
    tag_id: str, payload: TagUpdateRequest, context: Auth, service: Service
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
    except TagNotFoundError as exc:
        raise _not_found() from exc
    except TagConflictError as exc:
        raise _conflict("tag_duplicate_slug", "Tag slug already exists.") from exc
    except TagValidationError as exc:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="tag_validation_error",
            message=str(exc),
        ) from exc
    return _tag_response(tag)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Archive tag")
async def archive_tag(tag_id: str, context: Auth, service: Service) -> Response:
    try:
        await service.archive_tag(owner_user_id=context.user.id, tag_id=tag_id)
    except TagNotFoundError as exc:
        raise _not_found() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tags/{tag_id}/merge", response_model=TagResponse, summary="Merge tag")
async def merge_tag(
    tag_id: str, payload: TagMergeRequest, context: Auth, service: Service
) -> TagResponse:
    try:
        tag = await service.merge_tags(
            owner_user_id=context.user.id,
            source_tag_id=tag_id,
            target_tag_id=payload.target_tag_id,
        )
    except TagNotFoundError as exc:
        raise _not_found() from exc
    except TagConflictError as exc:
        raise _conflict("tag_merge_conflict", "Tags cannot be merged.") from exc
    return _tag_response(tag)


@router.get(
    "/tag-suggestions/review-queue",
    response_model=TagReviewQueueResponse,
    summary="List pending tag suggestions",
)
async def list_tag_review_queue(
    context: Auth,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TagReviewQueueResponse:
    assignments = await service.list_review_suggestions(
        owner_user_id=context.user.id, limit=limit, offset=offset
    )
    return TagReviewQueueResponse(items=[_assignment_response(item) for item in assignments])


@router.get(
    "/tag-jobs/metrics", response_model=TagsJobMetricsResponse, summary="Get tag job metrics"
)
async def tag_job_metrics(context: Auth, service: Service) -> TagsJobMetricsResponse:
    return await service.job_metrics(owner_user_id=context.user.id)


@router.post(
    "/content/{content_object_id}/tags",
    response_model=ContentTagAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign tag to content object",
    description="Returns 201 for a new assignment, 200 when the tag was already assigned.",
)
async def assign_tag(
    content_object_id: str,
    payload: ManualAssignTagRequest,
    response: Response,
    context: Auth,
    service: Service,
) -> ContentTagAssignmentResponse:
    try:
        assignment, created = await service.assign_tag_to_content(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            tag_id=payload.tag_id,
            assigned_by_user_id=context.user.id,
            reasoning=payload.reasoning,
        )
    except TagNotFoundError as exc:
        raise _not_found() from exc
    except TagConflictError as exc:
        raise _conflict(
            "tag_assignment_conflict", "Tag cannot be assigned to this content object."
        ) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return _assignment_response(assignment)


@router.get(
    "/content/{content_object_id}/tags",
    response_model=list[ContentTagAssignmentResponse],
    summary="List content tag assignments",
)
async def list_content_tags(
    content_object_id: str, context: Auth, service: Service
) -> list[ContentTagAssignmentResponse]:
    try:
        assignments = await service.list_tags_for_content(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            statuses=("accepted",),
        )
    except TagNotFoundError as exc:
        raise _not_found() from exc
    return [_assignment_response(assignment) for assignment in assignments]


@router.get(
    "/content/{content_object_id}/tags/jobs",
    response_model=TaggingJobListResponse,
    summary="List content tag suggestion jobs",
)
async def list_content_tag_jobs(
    content_object_id: str, context: Auth, service: Service
) -> TaggingJobListResponse:
    try:
        jobs = await service.list_jobs_for_content(
            owner_user_id=context.user.id, content_object_id=content_object_id
        )
    except TagNotFoundError as exc:
        raise _not_found() from exc
    return TaggingJobListResponse(items=[_job_response(job) for job in jobs])


@router.delete(
    "/content/{content_object_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove content tag assignment",
)
async def remove_content_tag(
    content_object_id: str, tag_id: str, context: Auth, service: Service
) -> Response:
    try:
        await service.remove_tag_from_content(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            tag_id=tag_id,
            assigned_by_user_id=context.user.id,
        )
    except TagNotFoundError as exc:
        raise _not_found() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/content/{content_object_id}/tags/suggest",
    response_model=TaggingJobResponse | ContentTagDryRunResponse,
    summary="Suggest content tags",
    description=(
        "Default: queue a background tagging job (poll `/tags/jobs`, results arrive as "
        "suggestions/accepted tags). `dry_run=true` returns suggestions synchronously "
        "without saving them (bounded by a short AI timeout)."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "AI tagging is disabled."},
        503: {"model": ErrorResponse, "description": "AI service unavailable."},
    },
)
async def suggest_content_tags(
    content_object_id: str,
    payload: SuggestContentTagsRequest,
    request: Request,
    context: Auth,
    service: Service,
) -> TaggingJobResponse | ContentTagDryRunResponse:
    if not payload.dry_run:
        try:
            job = await service.enqueue_content_tag_suggestions(
                owner_user_id=context.user.id, content_object_id=content_object_id
            )
        except TaggingDisabledError as exc:
            raise ai_disabled_error(AI_DISABLED_MESSAGE) from exc
        except TagNotFoundError as exc:
            raise _not_found() from exc
        return TaggingJobResponse(job_id=job.id, status=job.status)

    ai = get_ai_client(service.settings) if tagging_enabled(service.settings) else None
    if ai is None:
        raise ai_disabled_error(AI_DISABLED_MESSAGE)
    tagging_input = await load_tagging_input(
        service.session,
        request.app.state.storage,
        owner_user_id=context.user.id,
        content_object_id=content_object_id,
    )
    if tagging_input is None:
        raise _not_found()
    await service.session.commit()  # release the DB connection before the AI call
    suggestions = await interactive_ai(
        generate_suggestions(ai, service.settings, tagging_input, max_tags=payload.max_tags),
        operation="tags.suggest.dry_run",
    )
    return ContentTagDryRunResponse(
        content_object_id=content_object_id,
        suggestions=[
            ContentTagSuggestionResponse.model_validate(suggestion, from_attributes=True)
            for suggestion in suggestions
        ],
    )


@router.get(
    "/content/{content_object_id}/tags/suggestions",
    response_model=list[ContentTagAssignmentResponse],
    summary="List pending content tag suggestions",
)
async def list_suggestions(
    content_object_id: str, context: Auth, service: Service
) -> list[ContentTagAssignmentResponse]:
    try:
        assignments = await service.list_tags_for_content(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            statuses=("suggested",),
        )
    except TagNotFoundError as exc:
        raise _not_found() from exc
    return [_assignment_response(assignment) for assignment in assignments]


@router.post(
    "/content/{content_object_id}/tags/suggestions/{assignment_id}/accept",
    response_model=ContentTagAssignmentResponse,
    summary="Accept tag suggestion",
)
async def accept_suggestion(
    content_object_id: str, assignment_id: str, context: Auth, service: Service
) -> ContentTagAssignmentResponse:
    try:
        assignment = await service.accept_suggestion(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
            assigned_by_user_id=context.user.id,
        )
    except TagNotFoundError as exc:
        raise _not_found() from exc
    except TagConflictError as exc:
        raise _conflict("tag_suggestion_conflict", "Tag suggestion cannot be accepted.") from exc
    return _assignment_response(assignment)


@router.post(
    "/content/{content_object_id}/tags/suggestions/{assignment_id}/reject",
    response_model=ContentTagAssignmentResponse,
    summary="Reject tag suggestion",
)
async def reject_suggestion(
    content_object_id: str, assignment_id: str, context: Auth, service: Service
) -> ContentTagAssignmentResponse:
    try:
        assignment = await service.reject_suggestion(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
            assigned_by_user_id=context.user.id,
        )
    except TagNotFoundError as exc:
        raise _not_found() from exc
    except TagConflictError as exc:
        raise _conflict("tag_suggestion_conflict", "Tag suggestion cannot be rejected.") from exc
    return _assignment_response(assignment)
