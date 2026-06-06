from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.app_note import note_card_to_app_note
from app.modules.content.schemas import FileUploadResponse, NoteCardResponse
from app.modules.content.service import ContentService, UploadedContent
from app.modules.telegram_integration.infrastructure.repositories import TelegramIngestRepository
from app.modules.telegram_integration.schemas import (
    TelegramIngestMode,
    TelegramIngestPayload,
    TelegramIngestResponse,
    TelegramIngestStatus,
    TelegramStatusResponse,
)


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
    ) -> None:
        self.session = session
        self.content = content_service
        self.repo = TelegramIngestRepository(session)

    async def status(self, *, telegram_user_id: str) -> TelegramStatusResponse:
        user = await self.repo.get_user_by_telegram_id(telegram_user_id)
        if user is None:
            return TelegramStatusResponse(linked=False)
        return TelegramStatusResponse(
            linked=True,
            user_id=user.id,
            display_name=user.display_name,
        )

    async def ingest(
        self,
        *,
        payload: TelegramIngestPayload,
        uploaded: UploadedContent | None,
    ) -> TelegramIngestResponse:
        user = await self.repo.get_user_by_telegram_id(payload.telegram_user_id)
        if user is None:
            raise TelegramUserNotLinkedError

        if payload.target_collection_id is not None:
            card = await self._append_to_collection(
                owner_user_id=user.id,
                target_id=payload.target_collection_id,
                payload=payload,
                uploaded=uploaded,
            )
            return self._response(status="collection_updated", mode="default", card=card)

        card = await self._create_standalone(
            owner_user_id=user.id,
            payload=payload,
            uploaded=uploaded,
        )
        return self._response(status="saved", mode="default", card=card)

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
            card = await self.content.create_note(
                owner_user_id=owner_user_id,
                media_type="link" if payload.material_type == "link" else "text",
                text=text or "",
                title=title,
                folder_path=None,
                tag_names=[],
                file_upload_ids=[],
            )
            return await self._attach_source_and_reload(
                owner_user_id=owner_user_id,
                card=card,
                payload=payload,
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
            card = await self.content.create_note(
                owner_user_id=owner_user_id,
                media_type="text",
                text=text,
                title=title,
                folder_path=None,
                tag_names=[],
                file_upload_ids=[upload.files[0].id],
            )
            return await self._attach_source_and_reload(
                owner_user_id=owner_user_id,
                card=card,
                payload=payload,
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
        return await self._attach_source_and_reload(
            owner_user_id=owner_user_id,
            card=uploaded_card,
            payload=payload,
        )

    async def _attach_source_and_reload(
        self,
        *,
        owner_user_id: str,
        card: NoteCardResponse,
        payload: TelegramIngestPayload,
    ) -> NoteCardResponse:
        if payload.source is None:
            return card
        await self.content.attach_source_metadata(
            owner_user_id=owner_user_id,
            content_object_id=card.id,
            source=payload.source.model_dump(mode="python"),
        )
        return await self.content.get_note(owner_user_id=owner_user_id, slug=card.slug)

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
