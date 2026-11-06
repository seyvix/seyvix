"""Internal API for the telegram-bot service (the bot has no database access).

Every endpoint requires `Authorization: Bearer <TELEGRAM_INTERNAL_TOKEN>`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.core.config import get_settings
from app.modules.auth.access import (
    AccessDeniedError,
    AccessGrantExistsError,
    AccessGrantNotFoundError,
    AccessService,
    access_denied_details,
    is_admin_telegram_id,
)
from app.modules.auth.presentation.rest.admin_router import (
    grant_exists_error,
    grant_not_found_error,
)
from app.modules.auth.schemas import AccessGrantResponse, AccessListResponse
from app.modules.auth.security import tokens_equal
from app.modules.content.presentation.rest.router import get_content_service
from app.modules.content.service import ContentService
from app.modules.content.uploads import spool_upload_files
from app.modules.telegram_integration.schemas import (
    MAX_INGEST_FILES,
    BotModeRequest,
    BotStateResponse,
    FinishCollectionResponse,
    InternalAccessGrantRequest,
    InternalAccessRevokeRequest,
    InternalAccessRevokeResponse,
    ReminderClaimRequest,
    ReminderClaimResponse,
    TelegramIngestRequest,
    TelegramIngestResponse,
    TelegramUserStatusResponse,
)
from app.modules.telegram_integration.service import (
    TelegramIngestService,
    TelegramUserNotLinkedError,
    TelegramUserStatusService,
)
from app.modules.telegram_integration.state import BotStateStore, state_response


def verify_internal_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().telegram_internal_token
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not tokens_equal(token.strip(), expected):
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_telegram_integration_token",
            message="Invalid Telegram integration token.",
        )


router = APIRouter(
    prefix="/integrations/telegram",
    tags=["integrations"],
    dependencies=[Depends(verify_internal_token)],
)

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _access_denied(exc: AccessDeniedError) -> AppError:
    return AppError(
        status_code=status.HTTP_403_FORBIDDEN,
        code="access_denied",
        message="This Telegram user is not allowed to use Seyvix.",
        details=access_denied_details(exc.telegram_user_id, exc.username),
    )


def _require_admin(actor_telegram_id: int) -> None:
    if not is_admin_telegram_id(actor_telegram_id):
        raise AppError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="admin_required",
            message="Administrator access is required.",
        )


@router.get(
    "/users/{telegram_user_id}",
    response_model=TelegramUserStatusResponse,
    summary="Access and link status of a Telegram user",
)
async def get_user_status(
    telegram_user_id: int,
    session: SessionDep,
    username: Annotated[str | None, Query(max_length=64)] = None,
) -> TelegramUserStatusResponse:
    return await TelegramUserStatusService(session).status(
        telegram_user_id=telegram_user_id,
        username=username,
    )


@router.get("/state/{telegram_user_id}", response_model=BotStateResponse, summary="Bot state")
async def get_state(telegram_user_id: int, session: SessionDep) -> BotStateResponse:
    state = await BotStateStore(session).get_or_create(telegram_user_id)
    response = state_response(state)
    await session.commit()
    return response


@router.put(
    "/state/{telegram_user_id}/mode",
    response_model=BotStateResponse,
    summary="Set the bot saving mode",
)
async def set_mode(
    telegram_user_id: int,
    payload: BotModeRequest,
    session: SessionDep,
) -> BotStateResponse:
    state = await BotStateStore(session).set_mode(telegram_user_id, payload.mode)
    response = state_response(state)
    await session.commit()
    return response


@router.post(
    "/state/{telegram_user_id}/finish",
    response_model=FinishCollectionResponse,
    summary="Finish the manual collection",
)
async def finish_collection(
    telegram_user_id: int,
    session: SessionDep,
) -> FinishCollectionResponse:
    finished, state = await BotStateStore(session).finish_collection(telegram_user_id)
    response = FinishCollectionResponse(finished=finished, state=state_response(state))
    await session.commit()
    return response


@router.post(
    "/reminders/claim",
    response_model=ReminderClaimResponse,
    summary="Claim manual collections that need an 'still open?' reminder",
)
async def claim_reminders(
    payload: ReminderClaimRequest,
    session: SessionDep,
) -> ReminderClaimResponse:
    ids = await BotStateStore(session).claim_due_reminders(idle_seconds=payload.idle_seconds)
    await session.commit()
    return ReminderClaimResponse(telegram_user_ids=ids)


@router.get("/access", response_model=AccessListResponse, summary="Admin: list access grants")
async def list_access(
    actor_telegram_id: Annotated[int, Query(gt=0)],
    session: SessionDep,
) -> AccessListResponse:
    _require_admin(actor_telegram_id)
    return await AccessService(session).list_grants()


@router.post(
    "/access",
    response_model=AccessGrantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: allow a Telegram user",
)
async def grant_access(
    payload: InternalAccessGrantRequest,
    session: SessionDep,
) -> AccessGrantResponse:
    _require_admin(payload.actor_telegram_id)
    try:
        return await AccessService(session).create_grant(
            telegram_user_id=payload.telegram_user_id,
            username=payload.username,
            note=payload.note,
            created_by_telegram_id=payload.actor_telegram_id,
        )
    except AccessGrantExistsError as exc:
        raise grant_exists_error() from exc


@router.post(
    "/access/revoke",
    response_model=InternalAccessRevokeResponse,
    summary="Admin: revoke access (signs the user out everywhere)",
)
async def revoke_access(
    payload: InternalAccessRevokeRequest,
    session: SessionDep,
) -> InternalAccessRevokeResponse:
    _require_admin(payload.actor_telegram_id)
    try:
        revoked = await AccessService(session).delete_grant_by_identity(
            telegram_user_id=payload.telegram_user_id,
            username=payload.username,
        )
    except AccessGrantNotFoundError as exc:
        raise grant_not_found_error() from exc
    return InternalAccessRevokeResponse(sessions_revoked=revoked)


@router.post(
    "/ingest",
    response_model=TelegramIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save Telegram messages as notes",
    description=(
        "Multipart: `payload` (JSON TelegramIngestRequest) and up to "
        f"{MAX_INGEST_FILES} `files` referenced by `parts[].file_index`. Files are streamed to "
        "disk; each is limited to MAX_UPLOAD_BYTES (413)."
    ),
)
async def ingest(
    session: SessionDep,
    content_service: Annotated[ContentService, Depends(get_content_service)],
    payload: Annotated[str, Form(max_length=2_000_000)],
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> TelegramIngestResponse:
    try:
        request = TelegramIngestRequest.model_validate_json(payload)
    except ValidationError as exc:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="invalid_telegram_ingest_payload",
            message="Telegram ingest payload is invalid.",
            details=[
                {"message": error["msg"], "location": list(error["loc"])} for error in exc.errors()
            ],
        ) from exc
    uploads = files or []
    if len(uploads) > MAX_INGEST_FILES:
        raise AppError(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            code="too_many_files",
            message=f"At most {MAX_INGEST_FILES} files per request.",
        )
    indexes = request.file_indexes()
    if any(index >= len(uploads) for index in indexes) or len(set(indexes)) != len(indexes):
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="invalid_file_index",
            message="Every file_index must reference a distinct uploaded file.",
        )
    service = TelegramIngestService(session=session, content_service=content_service)
    async with spool_upload_files(uploads, max_bytes=get_settings().max_upload_bytes) as spooled:
        try:
            return await service.ingest(request=request, files=spooled)
        except AccessDeniedError as exc:
            raise _access_denied(exc) from exc
        except TelegramUserNotLinkedError as exc:
            raise AppError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="telegram_user_not_linked",
                message="Telegram user is not linked to a Seyvix account.",
            ) from exc
