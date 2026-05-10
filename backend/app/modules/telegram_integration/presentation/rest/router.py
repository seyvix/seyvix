from __future__ import annotations

from datetime import datetime
from typing import Annotated

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.core.config import get_settings
from app.modules.content.presentation.rest.router import get_content_service
from app.modules.content.service import ContentService, UploadedContent
from app.modules.telegram_integration.schemas import (
    TelegramFinishRequest,
    TelegramFinishResponse,
    TelegramIngestPayload,
    TelegramIngestResponse,
    TelegramMaterialType,
    TelegramModeRequest,
    TelegramModeResponse,
)
from app.modules.telegram_integration.service import (
    TelegramCollectionNotFoundError,
    TelegramIngestService,
    TelegramUserNotLinkedError,
)
from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/integrations/telegram", tags=["integrations"])


def _verify_internal_token(authorization: str | None) -> None:
    settings = get_settings()
    expected = settings.telegram_internal_token or settings.telegram_bot_token
    scheme, _, token = (authorization or "").partition(" ")
    if not expected or scheme.lower() != "bearer" or token != expected:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_telegram_integration_token",
            message="Invalid Telegram integration token.",
        )


def get_telegram_ingest_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    content_service: Annotated[ContentService, Depends(get_content_service)],
) -> TelegramIngestService:
    settings = get_settings()
    return TelegramIngestService(
        session=session,
        content_service=content_service,
        default_group_window_seconds=settings.telegram_default_group_window_seconds,
    )


def _raise_integration_error(exc: Exception) -> None:
    if isinstance(exc, TelegramUserNotLinkedError):
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="telegram_user_not_linked",
            message="Telegram user is not linked to a Seyvix account.",
        ) from exc
    if isinstance(exc, TelegramCollectionNotFoundError):
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="telegram_collection_not_found",
            message="Telegram collection was not found.",
        ) from exc
    raise exc


@router.post(
    "/ingest",
    response_model=TelegramIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Telegram message",
    description=(
        "Internal endpoint used by the Telegram bot service. It accepts Telegram message "
        "metadata, optional text/caption, and an optional downloaded file, then creates a "
        "regular Seyvix note or collection item for the linked Telegram user."
    ),
)
async def ingest_telegram_message(
    service: Annotated[TelegramIngestService, Depends(get_telegram_ingest_service)],
    authorization: Annotated[str | None, Header()] = None,
    telegram_user_id: Annotated[str, Form(max_length=64)] = "",
    telegram_chat_id: Annotated[str, Form(max_length=64)] = "",
    telegram_message_id: Annotated[str, Form(max_length=64)] = "",
    material_type: Annotated[TelegramMaterialType, Form()] = "text",
    message_date: Annotated[str | None, Form()] = None,
    text: Annotated[str | None, Form()] = None,
    caption: Annotated[str | None, Form()] = None,
    filename: Annotated[str | None, Form(max_length=512)] = None,
    mime_type: Annotated[str | None, Form(max_length=255)] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> TelegramIngestResponse:
    _verify_internal_token(authorization)
    parsed_message_date = datetime.fromisoformat(message_date) if message_date else None
    upload = None
    if file is not None:
        upload = UploadedContent(
            filename=filename or file.filename or "telegram-file",
            content_type=mime_type or file.content_type,
            data=await file.read(),
        )
    payload = TelegramIngestPayload(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        material_type=material_type,
        message_date=parsed_message_date,
        text=text,
        caption=caption,
        filename=filename,
        mime_type=mime_type,
    )
    try:
        return await service.ingest(payload=payload, uploaded=upload)
    except (TelegramUserNotLinkedError, TelegramCollectionNotFoundError) as exc:
        _raise_integration_error(exc)
        raise


@router.post(
    "/mode",
    response_model=TelegramModeResponse,
    summary="Set Telegram ingest mode",
    description="Internal endpoint used by the bot to switch between default and grouped modes.",
)
async def set_telegram_mode(
    payload: TelegramModeRequest,
    service: Annotated[TelegramIngestService, Depends(get_telegram_ingest_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> TelegramModeResponse:
    _verify_internal_token(authorization)
    try:
        mode = await service.set_mode(
            telegram_user_id=payload.telegram_user_id,
            mode=payload.mode,
        )
        return TelegramModeResponse(mode=mode)
    except TelegramUserNotLinkedError as exc:
        _raise_integration_error(exc)
        raise


@router.post(
    "/finish",
    response_model=TelegramFinishResponse,
    summary="Finish Telegram grouped collection",
    description="Internal endpoint used by the bot when a user sends /finish.",
)
async def finish_telegram_collection(
    payload: TelegramFinishRequest,
    service: Annotated[TelegramIngestService, Depends(get_telegram_ingest_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> TelegramFinishResponse:
    _verify_internal_token(authorization)
    try:
        await service.finish_collection(telegram_user_id=payload.telegram_user_id)
        return TelegramFinishResponse(status="finished")
    except TelegramUserNotLinkedError as exc:
        _raise_integration_error(exc)
        raise
