from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.modules.content.app_note import note_card_to_app_note
from app.modules.content.schemas import FileUploadResponse, NoteCardResponse
from app.modules.content.service import ContentService, UploadedContent
from app.modules.telegram_integration.infrastructure.repositories import TelegramIngestRepository
from app.modules.telegram_integration.models import TelegramIngestState
from app.modules.telegram_integration.schemas import (
    TelegramIngestMode,
    TelegramIngestPayload,
    TelegramIngestResponse,
    TelegramIngestStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TelegramUserNotLinkedError(Exception):
    pass


class TelegramCollectionNotFoundError(Exception):
    pass


class TelegramIngestService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        content_service: ContentService,
        default_group_window_seconds: int,
    ) -> None:
        self.session = session
        self.content = content_service
        self.repo = TelegramIngestRepository(session)
        self.default_group_window = timedelta(seconds=default_group_window_seconds)

    async def set_mode(
        self, *, telegram_user_id: str, mode: TelegramIngestMode
    ) -> TelegramIngestMode:
        user = await self.repo.get_user_by_telegram_id(telegram_user_id)
        if user is None:
            raise TelegramUserNotLinkedError
        state = await self.repo.get_or_create_state(user.id)
        state.mode = mode
        if mode == "default":
            state.active_collection_id = None
        else:
            state.default_group_collection_id = None
            state.last_message_at = None
        await self.session.commit()
        return mode

    async def finish_collection(self, *, telegram_user_id: str) -> None:
        user = await self.repo.get_user_by_telegram_id(telegram_user_id)
        if user is None:
            raise TelegramUserNotLinkedError
        state = await self.repo.get_or_create_state(user.id)
        state.active_collection_id = None
        state.default_group_collection_id = None
        state.last_message_at = None
        await self.session.commit()

    async def ingest(
        self,
        *,
        payload: TelegramIngestPayload,
        uploaded: UploadedContent | None,
    ) -> TelegramIngestResponse:
        user = await self.repo.get_user_by_telegram_id(payload.telegram_user_id)
        if user is None:
            raise TelegramUserNotLinkedError

        state = await self.repo.get_or_create_state(user.id)
        mode = self._mode(state)
        message_at = payload.message_date or datetime.now(UTC)
        if mode == "grouped_notes":
            return await self._ingest_grouped(
                owner_user_id=user.id,
                state=state,
                payload=payload,
                uploaded=uploaded,
                message_at=message_at,
            )
        return await self._ingest_default(
            owner_user_id=user.id,
            state=state,
            payload=payload,
            uploaded=uploaded,
            message_at=message_at,
        )

    async def _ingest_default(
        self,
        *,
        owner_user_id: str,
        state: TelegramIngestState,
        payload: TelegramIngestPayload,
        uploaded: UploadedContent | None,
        message_at: datetime,
    ) -> TelegramIngestResponse:
        target_id = (
            state.default_group_collection_id
            if self._is_inside_default_window(state=state, message_at=message_at)
            else None
        )
        if target_id is None:
            card = await self._create_standalone(
                owner_user_id=owner_user_id,
                payload=payload,
                uploaded=uploaded,
            )
            state.default_group_collection_id = card.id
            state.last_message_at = message_at
            await self.session.commit()
            return self._response(status="saved", mode="default", card=card)

        card = await self._append_to_collection(
            owner_user_id=owner_user_id,
            target_id=target_id,
            payload=payload,
            uploaded=uploaded,
        )
        state.default_group_collection_id = card.id
        state.last_message_at = message_at
        await self.session.commit()
        return self._response(status="collection_updated", mode="default", card=card)

    async def _ingest_grouped(
        self,
        *,
        owner_user_id: str,
        state: TelegramIngestState,
        payload: TelegramIngestPayload,
        uploaded: UploadedContent | None,
        message_at: datetime,
    ) -> TelegramIngestResponse:
        if state.active_collection_id is None:
            card = await self._create_standalone(
                owner_user_id=owner_user_id,
                payload=payload,
                uploaded=uploaded,
            )
            state.active_collection_id = card.id
            state.last_message_at = message_at
            await self.session.commit()
            return self._response(status="collection_started", mode="grouped_notes", card=card)

        card = await self._append_to_collection(
            owner_user_id=owner_user_id,
            target_id=state.active_collection_id,
            payload=payload,
            uploaded=uploaded,
        )
        state.active_collection_id = card.id
        state.last_message_at = message_at
        await self.session.commit()
        return self._response(status="collection_updated", mode="grouped_notes", card=card)

    async def _append_to_collection(
        self,
        *,
        owner_user_id: str,
        target_id: str,
        payload: TelegramIngestPayload,
        uploaded: UploadedContent | None,
    ) -> NoteCardResponse:
        target = await self.content.content.get_by_id(
            owner_user_id=owner_user_id,
            object_id=target_id,
        )
        if target is None:
            raise TelegramCollectionNotFoundError
        child = await self._create_standalone(
            owner_user_id=owner_user_id,
            payload=payload,
            uploaded=uploaded,
        )
        return await self.content.merge_notes(
            owner_user_id=owner_user_id,
            target_slug=target.slug,
            source_slugs=[child.slug],
            title=target.title,
        )

    async def _create_standalone(
        self,
        *,
        owner_user_id: str,
        payload: TelegramIngestPayload,
        uploaded: UploadedContent | None,
    ) -> NoteCardResponse:
        text = self._message_text(payload)
        title = self._title(payload=payload, uploaded=uploaded, text=text)
        if uploaded is None:
            return await self.content.create_note(
                owner_user_id=owner_user_id,
                media_type="link" if payload.material_type == "link" else "text",
                text=text or "",
                title=title,
                folder_path=None,
                tag_names=[],
                file_upload_ids=[],
            )

        if text:
            upload = await self.content.upload_files(
                owner_user_id=owner_user_id,
                files=[uploaded],
                title=title,
                folder_path=None,
                tag_names=[],
                create_or_attach_object=False,
                object_id=None,
            )
            if not isinstance(upload, FileUploadResponse) or not upload.files:
                raise TelegramCollectionNotFoundError
            return await self.content.create_note(
                owner_user_id=owner_user_id,
                media_type="text",
                text=text,
                title=title,
                folder_path=None,
                tag_names=[],
                file_upload_ids=[upload.files[0].id],
            )

        uploaded_card = await self.content.upload_files(
            owner_user_id=owner_user_id,
            files=[uploaded],
            title=title,
            folder_path=None,
            tag_names=[],
            create_or_attach_object=True,
            object_id=None,
        )
        if isinstance(uploaded_card, FileUploadResponse) or uploaded_card is None:
            raise TelegramCollectionNotFoundError
        return uploaded_card

    def _is_inside_default_window(
        self,
        *,
        state: TelegramIngestState,
        message_at: datetime,
    ) -> bool:
        if state.default_group_collection_id is None or state.last_message_at is None:
            return False
        previous = state.last_message_at
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=UTC)
        current = message_at if message_at.tzinfo is not None else message_at.replace(tzinfo=UTC)
        return current - previous <= self.default_group_window

    @staticmethod
    def _mode(state: TelegramIngestState) -> TelegramIngestMode:
        return "grouped_notes" if state.mode == "grouped_notes" else "default"

    @staticmethod
    def _message_text(payload: TelegramIngestPayload) -> str | None:
        value = payload.text if payload.text is not None else payload.caption
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _title(
        *,
        payload: TelegramIngestPayload,
        uploaded: UploadedContent | None,
        text: str | None,
    ) -> str | None:
        if text:
            return None
        if uploaded is not None:
            return Path(uploaded.filename).stem or uploaded.filename
        if payload.material_type == "link" and payload.text:
            return None
        return "Telegram message"

    @staticmethod
    def _response(
        *,
        status: TelegramIngestStatus,
        mode: TelegramIngestMode,
        card: NoteCardResponse,
    ) -> TelegramIngestResponse:
        return TelegramIngestResponse(status=status, mode=mode, note=note_card_to_app_note(card))
