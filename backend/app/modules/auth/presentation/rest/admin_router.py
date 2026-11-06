"""Admin API for the access allowlist (mounted at /admin/access)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.access import (
    AccessGrantExistsError,
    AccessGrantNotFoundError,
    AccessService,
)
from app.modules.auth.dependencies import require_admin
from app.modules.auth.schemas import (
    AccessGrantCreateRequest,
    AccessGrantResponse,
    AccessListResponse,
)
from app.modules.auth.service import AuthContext

router = APIRouter(
    prefix="/admin/access",
    tags=["admin"],
    responses={403: {"model": ErrorResponse, "description": "Administrator access required."}},
)

AdminDep = Annotated[AuthContext, Depends(require_admin)]


def get_access_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AccessService:
    return AccessService(session)


AccessServiceDep = Annotated[AccessService, Depends(get_access_service)]


def grant_exists_error() -> AppError:
    return AppError(
        status_code=status.HTTP_409_CONFLICT,
        code="access_grant_exists",
        message="This Telegram user or username is already allowed.",
    )


def grant_not_found_error() -> AppError:
    return AppError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="access_grant_not_found",
        message="Access grant not found.",
    )


@router.get("", response_model=AccessListResponse, summary="List access grants")
async def list_access(_: AdminDep, service: AccessServiceDep) -> AccessListResponse:
    return await service.list_grants()


@router.post(
    "",
    response_model=AccessGrantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Allow a Telegram user (by id or @username)",
    responses={409: {"model": ErrorResponse, "description": "Already allowed."}},
)
async def create_access(
    payload: AccessGrantCreateRequest,
    admin: AdminDep,
    service: AccessServiceDep,
) -> AccessGrantResponse:
    try:
        return await service.create_grant(
            telegram_user_id=payload.telegram_user_id,
            username=payload.username,
            note=payload.note,
            created_by_telegram_id=int(admin.user.telegram_id),
        )
    except AccessGrantExistsError as exc:
        raise grant_exists_error() from exc


@router.delete(
    "/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke access (also signs the user out everywhere)",
    responses={404: {"model": ErrorResponse, "description": "Grant not found."}},
)
async def delete_access(grant_id: str, _: AdminDep, service: AccessServiceDep) -> Response:
    try:
        await service.delete_grant(grant_id)
    except AccessGrantNotFoundError as exc:
        raise grant_not_found_error() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
