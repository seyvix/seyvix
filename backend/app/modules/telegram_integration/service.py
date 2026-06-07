from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.app_note import note_card_to_app_note
from app.modules.content.schemas import FileUploadResponse, NoteAssetResponse, NoteCardResponse
from app.modules.content.service import ContentService, UploadedContent
from app.modules.telegram_integration.infrastructure.repositories import TelegramIngestRepository
from app.modules.telegram_integration.schemas import (
    TelegramBatchIngestPart,
    TelegramIngestMode,
    TelegramIngestPayload,
    TelegramIngestResponse,
    TelegramIngestStatus,
    TelegramStatusResponse,
)

logger = logging.getLogger(__name__)


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

    async def ingest_batch(
        self,
        *,
        telegram_user_id: str,
        telegram_chat_id: str,
        parts: list[TelegramBatchIngestPart],
        uploaded: list[UploadedContent],
        target_collection_id: str | None = None,
    ) -> TelegramIngestResponse:
        user = await self.repo.get_user_by_telegram_id(telegram_user_id)
        if user is None:
            raise TelegramUserNotLinkedError
        if not parts:
            raise TelegramCollectionNotFoundError

        payloads = [
            TelegramIngestPayload(
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                telegram_message_id=part.telegram_message_id,
                material_type=part.material_type,
                message_date=part.message_date,
                text=part.text,
                caption=part.caption,
                filename=part.filename,
                mime_type=part.mime_type,
                source=part.source,
            )
            for part in parts
        ]
        uploads_by_part = [
            (
                uploaded[part.file_index]
                if part.file_index is not None and part.file_index < len(uploaded)
                else None
            )
            for part in parts
        ]
        if len(payloads) == 1:
            card = await self._create_standalone(
                owner_user_id=user.id,
                payload=payloads[0],
                uploaded=uploads_by_part[0],
            )
        else:
            card = await self._create_batch_standalone(
                owner_user_id=user.id,
                payloads=payloads,
                uploaded=uploads_by_part,
            )

        if target_collection_id is not None:
            card = await self._append_existing_to_collection(
                owner_user_id=user.id,
                target_id=target_collection_id,
                child=card,
            )
            return self._response(status="collection_updated", mode="default", card=card)
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
        return await self._append_existing_to_collection(
            owner_user_id=owner_user_id,
            target_id=target_id,
            child=child,
        )

    async def _append_existing_to_collection(
        self,
        *,
        owner_user_id: str,
        target_id: str,
        child: NoteCardResponse,
    ) -> NoteCardResponse:
        target = await self.content.content.get_by_id(
            owner_user_id=owner_user_id,
            object_id=target_id,
        )
        if target is None:
            raise TelegramCollectionNotFoundError
        return await self.content.merge_notes(
            owner_user_id=owner_user_id,
            target_slug=target.slug,
            source_slugs=[child.slug],
            title=target.title,
        )

    async def _create_batch_standalone(
        self,
        *,
        owner_user_id: str,
        payloads: list[TelegramIngestPayload],
        uploaded: list[UploadedContent | None],
    ) -> NoteCardResponse:
        text = self._batch_text(payloads)
        files = [item for item in uploaded if item is not None]
        card = await self.content.create_composite_note_from_uploads(
            owner_user_id=owner_user_id,
            files=files,
            text=text,
            title=self._batch_title(payloads=payloads, uploaded=files, text=text),
            folder_path=None,
            tag_names=[],
        )
        for payload, content_asset_id in self._batch_source_targets(
            card=card,
            payloads=payloads,
            uploaded=uploaded,
        ):
            await self._attach_source_and_reload(
                owner_user_id=owner_user_id,
                card=card,
                payload=payload,
                content_asset_id=content_asset_id,
            )
        return await self.content.get_note(owner_user_id=owner_user_id, slug=card.slug)

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
        content_asset_id: str | None = None,
    ) -> NoteCardResponse:
        if payload.source is None:
            logger.info(
                "Telegram source attach skipped user=%s object=%s message=%s reason=no_source",
                owner_user_id,
                card.id,
                payload.telegram_message_id,
            )
            return card
        logger.info(
            "Telegram source attach requested user=%s object=%s asset=%s message=%s "
            "source_external_id=%s source_title=%s",
            owner_user_id,
            card.id,
            content_asset_id,
            payload.telegram_message_id,
            payload.source.external_id,
            payload.source.title,
        )
        await self.content.attach_source_metadata(
            owner_user_id=owner_user_id,
            content_object_id=card.id,
            source=payload.source.model_dump(mode="python"),
            content_asset_id=content_asset_id,
        )
        await self.session.commit()
        return await self.content.get_note(owner_user_id=owner_user_id, slug=card.slug)

    @staticmethod
    def _batch_source_targets(
        *,
        card: NoteCardResponse,
        payloads: list[TelegramIngestPayload],
        uploaded: list[UploadedContent | None],
    ) -> list[tuple[TelegramIngestPayload, str | None]]:
        file_assets = [asset for asset in card.assets if asset.media_type != "text"]
        targets: list[tuple[TelegramIngestPayload, str | None]] = []
        object_source_external_id: str | None = None
        file_index = 0

        for payload, upload in zip(payloads, uploaded, strict=False):
            if payload.source is None:
                if upload is not None:
                    file_index += 1
                continue

            external_id = payload.source.external_id
            if object_source_external_id is None:
                object_source_external_id = external_id
                targets.append((payload, None))
                if upload is not None:
                    file_index += 1
                continue

            if upload is not None:
                asset = TelegramIngestService._file_asset_for_upload(
                    file_assets=file_assets,
                    upload=upload,
                    file_index=file_index,
                )
                file_index += 1
                if asset is not None and external_id != object_source_external_id:
                    targets.append((payload, asset.id))
                continue

            if external_id != object_source_external_id:
                targets.append((payload, None))

        return targets

    @staticmethod
    def _file_asset_for_upload(
        *,
        file_assets: list[NoteAssetResponse],
        upload: UploadedContent,
        file_index: int,
    ) -> NoteAssetResponse | None:
        matches = [
            asset
            for asset in file_assets
            if asset.filename == upload.filename and asset.mime_type == upload.content_type
        ]
        if len(matches) == 1:
            return matches[0]
        if file_index < len(file_assets):
            return file_assets[file_index]
        return None

    @staticmethod
    def _message_text(payload: TelegramIngestPayload) -> str | None:
        value = payload.text if payload.text is not None else payload.caption
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _batch_text(payloads: list[TelegramIngestPayload]) -> str | None:
        seen: set[str] = set()
        chunks: list[str] = []
        for payload in payloads:
            value = TelegramIngestService._message_text(payload)
            if value is None or value in seen:
                continue
            seen.add(value)
            chunks.append(value)
        return "\n\n".join(chunks) if chunks else None

    @staticmethod
    def _batch_title(
        *,
        payloads: list[TelegramIngestPayload],
        uploaded: list[UploadedContent],
        text: str | None,
    ) -> str | None:
        if text:
            return None
        if uploaded:
            return ""
        first_payload = payloads[0] if payloads else None
        if first_payload is not None and first_payload.material_type == "link":
            return None
        return "Telegram message"

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
            return ""
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
