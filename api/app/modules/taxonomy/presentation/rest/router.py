from __future__ import annotations

from typing import Annotated

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.taxonomy.models import TaxonomyClassificationJob
from app.modules.taxonomy.schemas import (
    TaxonomyAssignmentCreateRequest,
    TaxonomyAssignmentResponse,
    TaxonomyBreadcrumbResponse,
    TaxonomyCategoryDeleteRequest,
    TaxonomyCategoryDeleteResponse,
    TaxonomyCategoryCreateRequest,
    TaxonomyCategoryResponse,
    TaxonomyCategoryTreeItem,
    TaxonomyCategoryUpdateRequest,
    TaxonomyClassificationJobListResponse,
    TaxonomyClassificationJobResponse,
    TaxonomyClassificationRequest,
    TaxonomyClassificationResponse,
    TaxonomyInboxReclassifyResponse,
    TaxonomyInitializeRequest,
    TaxonomyInitializeResponse,
    TaxonomyInterestInitializeRequest,
    TaxonomyInterestOptionResponse,
    TaxonomyProfileDraftResponse,
    TaxonomyProfileImproveRequest,
    TaxonomyProfilePutRequest,
    TaxonomyProfileResponse,
    TaxonomySettingsPatchRequest,
    TaxonomySettingsResponse,
    TaxonomyTemplateDetailResponse,
    TaxonomyTemplateSummaryResponse,
)
from app.modules.taxonomy.service import (
    TaxonomyConflictError,
    TaxonomyLLMClassificationError,
    TaxonomyNotFoundError,
    TaxonomyPermissionError,
    TaxonomyService,
    TaxonomyValidationError,
)
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


def get_taxonomy_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TaxonomyService:
    return TaxonomyService(session)


def _not_found(message: str = "Taxonomy resource not found.") -> AppError:
    return AppError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="taxonomy_not_found",
        message=message,
    )


def _conflict(message: str) -> AppError:
    return AppError(status_code=status.HTTP_409_CONFLICT, code="taxonomy_conflict", message=message)


def _validation_error(message: str) -> AppError:
    return AppError(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="validation_error",
        message=message,
    )


def _forbidden(message: str) -> AppError:
    return AppError(
        status_code=status.HTTP_403_FORBIDDEN,
        code="taxonomy_forbidden",
        message=message,
    )


def _classification_job_response(
    job: TaxonomyClassificationJob,
) -> TaxonomyClassificationJobResponse:
    return TaxonomyClassificationJobResponse(
        id=job.id,
        content_object_id=job.content_object_id,
        job_type=job.job_type,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        result_status=job.result_status,
        assignment_id=job.assignment_id,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get(
    "/settings",
    response_model=TaxonomySettingsResponse,
    summary="Get taxonomy user settings",
    responses={401: {"model": ErrorResponse}},
)
async def get_settings(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomySettingsResponse:
    settings_model = await service.get_user_settings(owner_user_id=context.user.id)
    return service.settings_response(settings_model)


@router.patch(
    "/settings",
    response_model=TaxonomySettingsResponse,
    summary="Update taxonomy user settings",
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def update_settings(
    payload: TaxonomySettingsPatchRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomySettingsResponse:
    settings_model = await service.update_user_settings(
        owner_user_id=context.user.id,
        category_profile_editing_enabled=payload.category_profile_editing_enabled,
        trash_enabled=payload.trash_enabled,
        trash_retention_days=payload.trash_retention_days,
    )
    return service.settings_response(settings_model)


@router.get(
    "/categories/tree",
    response_model=list[TaxonomyCategoryTreeItem],
    summary="Get taxonomy category tree",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_category_tree(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
    root_id: Annotated[str | None, Query(max_length=36)] = None,
    max_depth: Annotated[int | None, Query(ge=0)] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> list[TaxonomyCategoryTreeItem]:
    try:
        return await service.get_tree(
            owner_user_id=context.user.id,
            root_id=root_id,
            max_depth=max_depth,
            include_archived=include_archived,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category not found.") from exc


@router.get(
    "/categories/search",
    response_model=list[TaxonomyCategoryResponse],
    summary="Search taxonomy categories",
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def search_categories(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
    q: Annotated[str, Query(min_length=1, max_length=255)],
    include_archived: Annotated[bool, Query()] = False,
) -> list[TaxonomyCategoryResponse]:
    try:
        categories = await service.search_categories(
            owner_user_id=context.user.id,
            query_text=q,
            include_archived=include_archived,
        )
    except TaxonomyValidationError as exc:
        raise _validation_error("Search query must not be empty.") from exc
    return [service.category_response(category) for category in categories]


@router.get(
    "/categories/{category_id}",
    response_model=TaxonomyCategoryResponse,
    summary="Get taxonomy category",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_category(
    category_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyCategoryResponse:
    try:
        category = await service.get_category(
            owner_user_id=context.user.id,
            category_id=category_id,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category not found.") from exc
    return service.category_response(category)


@router.get(
    "/categories/{category_id}/breadcrumbs",
    response_model=list[TaxonomyBreadcrumbResponse],
    summary="Get taxonomy category breadcrumbs",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_category_breadcrumbs(
    category_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> list[TaxonomyBreadcrumbResponse]:
    try:
        return await service.get_breadcrumbs(
            owner_user_id=context.user.id,
            category_id=category_id,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category not found.") from exc


@router.post(
    "/categories",
    response_model=TaxonomyCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create taxonomy category",
    responses={
        201: {"description": "Taxonomy category created."},
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_category(
    payload: TaxonomyCategoryCreateRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyCategoryResponse:
    try:
        category = await service.create_category(
            owner_user_id=context.user.id,
            parent_id=payload.parent_id,
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            sort_order=payload.sort_order,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Parent category not found.") from exc
    except TaxonomyConflictError as exc:
        raise _conflict("Category slug or path already exists.") from exc
    except TaxonomyValidationError as exc:
        raise _validation_error("Invalid taxonomy category data.") from exc
    return service.category_response(category)


@router.patch(
    "/categories/{category_id}",
    response_model=TaxonomyCategoryResponse,
    summary="Update taxonomy category",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_category(
    category_id: str,
    payload: TaxonomyCategoryUpdateRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyCategoryResponse:
    try:
        category = await service.update_category(
            owner_user_id=context.user.id,
            category_id=category_id,
            name=payload.name,
            description=payload.description,
            slug=payload.slug,
            sort_order=payload.sort_order,
            is_archived=payload.is_archived,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category not found.") from exc
    except TaxonomyConflictError as exc:
        raise _conflict("Category cannot be updated with the requested values.") from exc
    except TaxonomyValidationError as exc:
        raise _validation_error("Invalid taxonomy category data.") from exc
    return service.category_response(category)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive taxonomy category",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def archive_category(
    category_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> Response:
    try:
        await service.archive_category(owner_user_id=context.user.id, category_id=category_id)
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category not found.") from exc
    except TaxonomyConflictError as exc:
        raise _conflict("Category cannot be archived.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/categories/{category_id}/delete",
    response_model=TaxonomyCategoryDeleteResponse,
    summary="Delete taxonomy category",
    responses={
        200: {"description": "Category archived and content handled."},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def delete_category(
    category_id: str,
    payload: TaxonomyCategoryDeleteRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyCategoryDeleteResponse:
    try:
        return await service.delete_category(
            owner_user_id=context.user.id,
            category_id=category_id,
            delete_notes=payload.delete_notes,
            confirm_category_name=payload.confirm_category_name,
            confirm_delete_notes_text=payload.confirm_delete_notes_text,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category or inbox not found.") from exc
    except TaxonomyConflictError as exc:
        raise _conflict("Category cannot be deleted.") from exc
    except TaxonomyValidationError as exc:
        raise _validation_error("Dangerous category deletion requires confirmation.") from exc


@router.post(
    "/categories/{category_id}/restore",
    response_model=TaxonomyCategoryResponse,
    summary="Restore archived taxonomy category",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def restore_category(
    category_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyCategoryResponse:
    try:
        category = await service.restore_category(
            owner_user_id=context.user.id,
            category_id=category_id,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category not found.") from exc
    except TaxonomyConflictError as exc:
        raise _conflict("Category cannot be restored.") from exc
    return service.category_response(category)


@router.get(
    "/categories/{category_id}/profile",
    response_model=TaxonomyProfileResponse,
    summary="Get taxonomy category profile",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_profile(
    category_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyProfileResponse:
    try:
        profile = await service.get_profile(owner_user_id=context.user.id, category_id=category_id)
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category profile not found.") from exc
    return service.profile_response(profile)


@router.put(
    "/categories/{category_id}/profile",
    response_model=TaxonomyProfileResponse,
    summary="Create or update taxonomy category profile",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def put_profile(
    category_id: str,
    payload: TaxonomyProfilePutRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyProfileResponse:
    try:
        profile = await service.put_profile(
            owner_user_id=context.user.id,
            category_id=category_id,
            summary=payload.summary,
            keywords=payload.keywords,
            positive_examples=payload.positive_examples,
            negative_examples=payload.negative_examples,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category not found.") from exc
    except TaxonomyPermissionError as exc:
        raise _forbidden("Category profile editing is disabled in taxonomy settings.") from exc
    return service.profile_response(profile)


@router.post(
    "/categories/{category_id}/profile/improve",
    response_model=TaxonomyProfileDraftResponse,
    summary="Suggest taxonomy category profile improvements",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def suggest_profile_improvement(
    category_id: str,
    payload: TaxonomyProfileImproveRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyProfileDraftResponse:
    try:
        return await service.suggest_profile_improvement(
            owner_user_id=context.user.id,
            category_id=category_id,
            user_guidance=payload.user_guidance,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Category not found.") from exc
    except TaxonomyLLMClassificationError as exc:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="taxonomy_profile_llm_unavailable",
            message="LLM category profile improvement is unavailable.",
        ) from exc


@router.post(
    "/content/{content_object_id}/assignments",
    response_model=TaxonomyAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign content object to taxonomy category",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def create_assignment(
    content_object_id: str,
    payload: TaxonomyAssignmentCreateRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyAssignmentResponse:
    try:
        assignment = await service.create_manual_assignment(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            category_id=payload.category_id,
            reasoning=payload.reasoning,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Content object or category not found.") from exc
    return service.assignment_response(assignment)


@router.get(
    "/content/{content_object_id}/assignments",
    response_model=list[TaxonomyAssignmentResponse],
    summary="List content taxonomy assignments",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def list_assignments(
    content_object_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> list[TaxonomyAssignmentResponse]:
    try:
        assignments = await service.list_assignments(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Content object not found.") from exc
    return [service.assignment_response(assignment) for assignment in assignments]


@router.get(
    "/content/{content_object_id}/classification-jobs",
    response_model=TaxonomyClassificationJobListResponse,
    summary="List content taxonomy classification jobs",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def list_classification_jobs(
    content_object_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyClassificationJobListResponse:
    try:
        jobs = await service.list_classification_jobs(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Content object not found.") from exc
    return TaxonomyClassificationJobListResponse(
        items=[_classification_job_response(job) for job in jobs],
    )


@router.post(
    "/content/inbox/reclassify",
    response_model=TaxonomyInboxReclassifyResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Requeue inbox content for taxonomy classification",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def reclassify_inbox_content(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyInboxReclassifyResponse:
    try:
        return await service.enqueue_inbox_reclassification_jobs(owner_user_id=context.user.id)
    except TaxonomyNotFoundError as exc:
        raise _not_found("Inbox category not found.") from exc


@router.get(
    "/content/{content_object_id}/category",
    response_model=TaxonomyAssignmentResponse | None,
    summary="Get current content taxonomy category assignment",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_current_assignment(
    content_object_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyAssignmentResponse | None:
    try:
        assignment = await service.get_current_assignment(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Content object not found.") from exc
    return service.assignment_response(assignment) if assignment is not None else None


@router.post(
    "/content/{content_object_id}/classify",
    response_model=TaxonomyClassificationResponse,
    summary="Classify a content object using semantic taxonomy category candidates",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def classify_content_object(
    content_object_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
    payload: TaxonomyClassificationRequest | None = None,
) -> TaxonomyClassificationResponse:
    request = payload or TaxonomyClassificationRequest()
    try:
        return await service.classify_content_object_with_response(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            mode=request.mode,
            candidate_limit=request.candidate_limit,
            dry_run=request.dry_run,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Content object not found.") from exc
    except TaxonomyLLMClassificationError as exc:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="taxonomy_llm_classification_unavailable",
            message="LLM taxonomy classification is unavailable.",
        ) from exc


@router.post(
    "/content/{content_object_id}/assignments/{assignment_id}/accept",
    response_model=TaxonomyAssignmentResponse,
    summary="Accept taxonomy assignment",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def accept_assignment(
    content_object_id: str,
    assignment_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyAssignmentResponse:
    try:
        assignment = await service.accept_assignment(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Assignment not found.") from exc
    except TaxonomyConflictError as exc:
        raise _conflict("Assignment category is archived.") from exc
    return service.assignment_response(assignment)


@router.post(
    "/content/{content_object_id}/assignments/{assignment_id}/reject",
    response_model=TaxonomyAssignmentResponse,
    summary="Reject taxonomy assignment",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def reject_assignment(
    content_object_id: str,
    assignment_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyAssignmentResponse:
    try:
        assignment = await service.reject_assignment(
            owner_user_id=context.user.id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Assignment not found.") from exc
    return service.assignment_response(assignment)


@router.get(
    "/interest-options",
    response_model=list[TaxonomyInterestOptionResponse],
    summary="List taxonomy onboarding interest options",
    responses={401: {"model": ErrorResponse}},
)
async def list_interest_options(
    _: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> list[TaxonomyInterestOptionResponse]:
    return [
        TaxonomyInterestOptionResponse(
            slug=option.slug,
            name=option.name,
            description=option.description,
        )
        for option in service.list_interest_options()
    ]


@router.post(
    "/initialize/interests",
    response_model=TaxonomyInitializeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize current user's taxonomy from selected interests",
    responses={
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def initialize_taxonomy_from_interests(
    payload: TaxonomyInterestInitializeRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyInitializeResponse:
    try:
        result = await service.initialize_from_interests(
            owner_user_id=context.user.id,
            interest_slugs=payload.interest_slugs,
            custom_description=payload.custom_description,
        )
    except TaxonomyConflictError as exc:
        raise _conflict("Taxonomy already exists for this user.") from exc
    except TaxonomyValidationError as exc:
        raise _validation_error(
            "Select at least one known interest or describe your interests."
        ) from exc
    return TaxonomyInitializeResponse(
        owner_user_id=result.owner_user_id,
        template_slug=result.template_slug,
        created_categories_count=result.created_categories_count,
        created_profiles_count=result.created_profiles_count,
    )


@router.get(
    "/templates",
    response_model=list[TaxonomyTemplateSummaryResponse],
    summary="List taxonomy templates",
    responses={401: {"model": ErrorResponse}},
)
async def list_templates(
    _: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> list[TaxonomyTemplateSummaryResponse]:
    return [service.template_summary(template) for template in await service.list_templates()]


@router.get(
    "/templates/{template_slug}",
    response_model=TaxonomyTemplateDetailResponse,
    summary="Get taxonomy template",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_template(
    template_slug: str,
    _: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyTemplateDetailResponse:
    try:
        template = await service.get_template(template_slug=template_slug)
    except TaxonomyNotFoundError as exc:
        raise _not_found("Template not found.") from exc
    categories = await service.repository.list_template_categories(template_id=template.id)
    return service.template_detail(template, categories)


@router.post(
    "/initialize",
    response_model=TaxonomyInitializeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize current user's taxonomy from a template",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def initialize_taxonomy(
    payload: TaxonomyInitializeRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[TaxonomyService, Depends(get_taxonomy_service)],
) -> TaxonomyInitializeResponse:
    try:
        result = await service.initialize_from_template(
            owner_user_id=context.user.id,
            template_slug=payload.template_slug,
        )
    except TaxonomyNotFoundError as exc:
        raise _not_found("Template not found.") from exc
    except TaxonomyConflictError as exc:
        raise _conflict("Taxonomy already exists for this user.") from exc
    return TaxonomyInitializeResponse(
        owner_user_id=result.owner_user_id,
        template_slug=result.template_slug,
        created_categories_count=result.created_categories_count,
        created_profiles_count=result.created_profiles_count,
    )
