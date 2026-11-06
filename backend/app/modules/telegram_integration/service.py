from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.auth.access import AccessDeniedError, AccessService, is_admin_telegram_id
from app.modules.auth.models import User
from app.modules.content.app_note import note_card_to_app_note
from app.modules.content.schemas import FileUploadResponse, NoteAssetResponse, NoteCardResponse
from app.modules.content.service import ContentService, UploadedContent
from app.modules.telegram_integration.models import BOT_MODE_MANUAL_COLLECTION
from app.modules.telegram_integration.schemas import (
    TelegramIngestPart,
    TelegramIngestRequest,
    TelegramIngestResponse,
    TelegramIngestStatus,
    TelegramUserStatusResponse,
)
from app.modules.telegram_integration.state import BotStateStore

logger = get_logger(__name__)


class TelegramUserNotLinkedError(Exception):
    pass


class TelegramUserStatusService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.access = AccessService(session)

    async def status(
        self,
        *,
        telegram_user_id: int,
        username: str | None,
    ) -> TelegramUserStatusResponse:
        try:
            # Also binds a pending @username grant to this (Telegram-verified) id.
            await self.access.ensure_allowed(telegram_user_id, username, record_login=False)
            allowed = True
            await self.session.commit()
        except AccessDeniedError:
            allowed = False
        user = await _user_by_telegram_id(self.session, telegram_user_id)
        return TelegramUserStatusResponse(
            telegram_user_id=telegram_user_id,
            allowed=allowed,
            is_admin=is_admin_telegram_id(telegram_user_id),
            linked=user is not None and user.is_active,
            user_id=user.id if user is not None else None,
            display_name=user.display_name if user is not None else None,
        )


class TelegramIngestService:
    """Turns bot uploads into notes. Each group becomes one note; several groups in one request
    (a quick series in auto mode) are merged into the first; in manual-collection mode everything
    is merged into the user's active collection."""

    def __init__(self, *, session: AsyncSession, content_service: ContentService) -> None:
        self.session = session
        self.content = content_service
        self.access = AccessService(session)
        self.states = BotStateStore(session)

    async def ingest(
        self,
        *,
        request: TelegramIngestRequest,
        files: list[UploadedContent],
    ) -> TelegramIngestResponse:
        # Raises AccessDeniedError; checked on every save so revocation applies immediately.
        await self.access.ensure_allowed(request.telegram_user_id, None, record_login=False)
        user = await _user_by_telegram_id(self.session, request.telegram_user_id)
        if user is None or not user.is_active:
            raise TelegramUserNotLinkedError
        owner_id = user.id
        state = await self.states.get_or_create(request.telegram_user_id)
        manual = state.mode == BOT_MODE_MANUAL_COLLECTION
        expected_collection_id = state.active_collection_id if manual else None
        collection = None
        if expected_collection_id is not None:
            collection = await self.content.content.get_by_id(
                owner_user_id=owner_id,
                object_id=expected_collection_id,
            )
        await self.session.commit()

        cards = [
            await self._create_group_note(
                owner_user_id=owner_id,
                parts=group.parts,
                files=[
                    files[part.file_index] if part.file_index is not None else None
                    for part in group.parts
                ],
            )
            for group in request.groups
        ]

        status: TelegramIngestStatus = "saved"
        if collection is not None:
            card = await self._merge(owner_id, target_slug=collection.slug, sources=cards)
            status = "collection_updated"
        else:
            card = await self._merge(owner_id, target_slug=cards[0].slug, sources=cards[1:])
            if manual:
                status = "collection_started"
        if manual:
            await self.states.record_collection_item(
                request.telegram_user_id,
                expected_collection_id=expected_collection_id,
                collection_id=card.id,
            )
            await self.session.commit()
        logger.info(
            "telegram.ingest.saved",
            object_id=card.id,
            groups=len(request.groups),
            files=len(files),
            status=status,
        )
        return TelegramIngestResponse(status=status, note=note_card_to_app_note(card))

    async def _merge(
        self,
        owner_user_id: str,
        *,
        target_slug: str,
        sources: list[NoteCardResponse],
    ) -> NoteCardResponse:
        if not sources:
            return await self.content.get_note(owner_user_id=owner_user_id, slug=target_slug)
        target = await self.content.get_note(owner_user_id=owner_user_id, slug=target_slug)
        return await self.content.merge_notes(
            owner_user_id=owner_user_id,
            target_slug=target_slug,
            source_slugs=[card.slug for card in sources],
            title=target.title,
        )

    async def _create_group_note(
        self,
        *,
        owner_user_id: str,
        parts: list[TelegramIngestPart],
        files: list[UploadedContent | None],
    ) -> NoteCardResponse:
        if len(parts) == 1:
            return await self._create_single_note(
                owner_user_id=owner_user_id,
                part=parts[0],
                uploaded=files[0],
            )
        text = _batch_text(parts)
        present_files = [item for item in files if item is not None]
        card = await self.content.create_composite_note_from_uploads(
            owner_user_id=owner_user_id,
            files=present_files,
            text=text,
            title=_batch_title(parts=parts, has_files=bool(present_files), text=text),
            folder_path=None,
            tag_names=[],
        )
        for part, content_asset_id in _batch_source_targets(card=card, parts=parts, files=files):
            await self._attach_source(
                owner_user_id=owner_user_id,
                card=card,
                part=part,
                content_asset_id=content_asset_id,
            )
        return await self.content.get_note(owner_user_id=owner_user_id, slug=card.slug)

    async def _create_single_note(
        self,
        *,
        owner_user_id: str,
        part: TelegramIngestPart,
        uploaded: UploadedContent | None,
    ) -> NoteCardResponse:
        text = _message_text(part)
        title = _title(part=part, has_file=uploaded is not None, text=text)
        if uploaded is None:
            card = await self.content.create_note(
                owner_user_id=owner_user_id,
                media_type="link" if part.material_type == "link" else "text",
                text=text or "",
                title=title,
                folder_path=None,
                tag_names=[],
                file_upload_ids=[],
            )
        elif text:
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
                raise RuntimeError("Content upload did not return a pending upload")
            card = await self.content.create_note(
                owner_user_id=owner_user_id,
                media_type="text",
                text=text,
                title=title,
                folder_path=None,
                tag_names=[],
                file_upload_ids=[upload.files[0].id],
            )
        else:
            created = await self.content.upload_files(
                owner_user_id=owner_user_id,
                files=[uploaded],
                title=title,
                folder_path=None,
                tag_names=[],
                create_or_attach_object=True,
                object_id=None,
            )
            if not isinstance(created, NoteCardResponse):
                raise RuntimeError("Content upload did not create a note")
            card = created
        if part.source is None:
            return card
        await self._attach_source(owner_user_id=owner_user_id, card=card, part=part)
        return await self.content.get_note(owner_user_id=owner_user_id, slug=card.slug)

    async def _attach_source(
        self,
        *,
        owner_user_id: str,
        card: NoteCardResponse,
        part: TelegramIngestPart,
        content_asset_id: str | None = None,
    ) -> None:
        if part.source is None:
            return
        await self.content.attach_source_metadata(
            owner_user_id=owner_user_id,
            content_object_id=card.id,
            source=part.source.model_dump(mode="python"),
            content_asset_id=content_asset_id,
        )
        await self.session.commit()


async def _user_by_telegram_id(session: AsyncSession, telegram_user_id: int) -> User | None:
    user: User | None = await session.scalar(
        select(User).where(User.telegram_id == str(telegram_user_id))
    )
    return user


def _batch_source_targets(
    *,
    card: NoteCardResponse,
    parts: list[TelegramIngestPart],
    files: list[UploadedContent | None],
) -> list[tuple[TelegramIngestPart, str | None]]:
    """Which source metadata goes to the note (first source) and which to individual assets
    (later parts of an album forwarded from a different message)."""
    file_assets = [asset for asset in card.assets if asset.media_type != "text"]
    targets: list[tuple[TelegramIngestPart, str | None]] = []
    object_external_id: str | None = None
    file_position = 0
    for part, upload in zip(parts, files, strict=True):
        asset: NoteAssetResponse | None = None
        if upload is not None:
            asset = _file_asset_for_upload(file_assets, upload, file_position)
            file_position += 1
        if part.source is None:
            continue
        external_id = part.source.external_id
        if object_external_id is None:
            object_external_id = external_id
            targets.append((part, None))
        elif external_id != object_external_id:
            if upload is None:
                targets.append((part, None))
            elif asset is not None:
                targets.append((part, asset.id))
    return targets


def _file_asset_for_upload(
    file_assets: list[NoteAssetResponse],
    upload: UploadedContent,
    position: int,
) -> NoteAssetResponse | None:
    matches = [
        asset
        for asset in file_assets
        if asset.filename == upload.filename and asset.mime_type == upload.content_type
    ]
    if len(matches) == 1:
        return matches[0]
    return file_assets[position] if position < len(file_assets) else None


def _message_text(part: TelegramIngestPart) -> str | None:
    value = part.text if part.text is not None else part.caption
    if value is None:
        return None
    return value.strip() or None


def _batch_text(parts: list[TelegramIngestPart]) -> str | None:
    chunks = list(dict.fromkeys(text for part in parts if (text := _message_text(part))))
    return "\n\n".join(chunks) if chunks else None


def _batch_title(
    *,
    parts: list[TelegramIngestPart],
    has_files: bool,
    text: str | None,
) -> str | None:
    if text:
        return None
    if has_files:
        return ""
    if parts[0].material_type == "link":
        return None
    return "Telegram message"


def _title(*, part: TelegramIngestPart, has_file: bool, text: str | None) -> str | None:
    # "" lets Content derive the title from the file instead of the transport filename.
    if text:
        return None
    if has_file:
        return ""
    if part.material_type == "link" and part.text:
        return None
    return "Telegram message"
