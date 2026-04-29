from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.taxonomy.schemas import (
    TaxonomyAssignmentCreateRequest,
    TaxonomyAssignmentResponse,
    TaxonomyBreadcrumbResponse,
    TaxonomyCategoryCreateRequest,
    TaxonomyCategoryResponse,
    TaxonomyCategoryTreeItem,
    TaxonomyCategoryUpdateRequest,
    TaxonomyInitializeRequest,
    TaxonomyInitializeResponse,
    TaxonomyProfilePutRequest,
    TaxonomyProfileResponse,
    TaxonomyTemplateDetailResponse,
    TaxonomyTemplateSummaryResponse,
)
from app.modules.taxonomy.service import (
    TaxonomyConflictError,
    TaxonomyNotFoundError,
    TaxonomyService,
    TaxonomyValidationError,
)

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
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        message=message,
    )


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
    return service.profile_response(profile)


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
