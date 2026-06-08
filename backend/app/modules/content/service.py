from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete as sql_delete
from sqlalchemy import or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import ContentObjectChangedPayload, EventEnvelope
from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.content.contracts import ContentClassificationInput
from app.modules.content.infrastructure.repositories import (
    ContentRepository,
    FileUploadRepository,
    TagRepository,
)
from app.modules.content.models import (
    ContentAsset,
    ContentCollectionItem,
    ContentFileUpload,
    ContentLinkSnapshotDecision,
    ContentObject,
    ContentObjectTag,
    ContentSource,
)
from app.modules.content.models import ContentTag as LegacyContentTag
from app.modules.content.schemas import (
    CollectionParentResponse,
    ContentTaxonomyCategoryResponse,
    DeferredLinkSnapshotsResponse,
    FileUploadResponse,
    FolderDetailResponse,
    FolderResponse,
    FolderTreeItem,
    FolderTreeResponse,
    NoteAssetResponse,
    NoteCardResponse,
    NoteListResponse,
    SnapshotViewResponse,
    SourceMetadataResponse,
    TagResponse,
    UploadedFileResponse,
)
from app.modules.content.storage import ContentStorage, StoredFile, slugify
from app.modules.search.schemas import SearchContentMatch
from app.modules.snapshots.service import SnapshotArtifactReference, SnapshotService
from app.modules.tags.models import Tag
from app.modules.tags.service import TagsService
from app.modules.taxonomy.models import TaxonomyCategory, TaxonomyContentAssignment
from app.modules.taxonomy.service import TaxonomyService
from app.platform.events.outbox import EventOutboxRepository
from app.platform.storage.factory import build_storage_backend
from app.platform.storage.repositories import StorageObjectRepository
from app.platform.storage.service import StorageBackend, StoredObject


def _note_path_ref_as_uuid(ref: str) -> str | None:
    """Return normalized UUID string if `ref` looks like a UUID, else None (treat as slug)."""
    try:
        return str(UUID(ref.strip()))
    except (ValueError, AttributeError):
        return None


logger = get_logger(__name__)
LINK_TITLE_FETCH_TIMEOUT_SECONDS = 2.5
LINK_TITLE_FETCH_MAX_CHARS = 200_000
AUTO_LINK_SNAPSHOT_LIMIT = 3
DEFERRED_LINK_SNAPSHOT_TTL = timedelta(hours=12)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


_TITLE_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_TITLE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_TITLE_CUSTOM_EMOJI_RE = re.compile(r"\{\{tg_emoji:[0-9]+\|([^}]+)\}\}")
_TITLE_INLINE_TAG_RE = re.compile(
    r"</?(?:u|b|i|s|em|strong|code|tg-spoiler)\b[^>]*>",
    re.IGNORECASE,
)
_TITLE_HEADING_PREFIX_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_TITLE_BLOCKQUOTE_PREFIX_RE = re.compile(r"^\s{0,3}>\s+")
_TITLE_TASK_PREFIX_RE = re.compile(r"^\s{0,3}[-*+]\s+\[[ xX]\]\s+")
_TITLE_LIST_PREFIX_RE = re.compile(r"^\s{0,3}[-*+]\s+")
_TITLE_BOLD_STAR_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_TITLE_BOLD_UNDERSCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
_TITLE_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_TITLE_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\*)(\S(?:[^*\n]*?\S)?)\*(?!\*)")
_TITLE_ITALIC_UNDERSCORE_RE = re.compile(
    r"(?<![A-Za-z0-9_])_(?!_)(\S(?:[^_\n]*?\S)?)_(?!_)(?![A-Za-z0-9_])",
)
_TITLE_INLINE_CODE_RE = re.compile(r"`+([^`]+?)`+")


def _strip_title_markdown(value: str) -> str:
    """Remove common Markdown / Telegram entity markers from a single-line title.

    Telegram custom emoji markers are replaced with their fallback emoji.
    Bold/italic/strike/code/link/heading/blockquote/list markers are unwrapped
    while the textual content is preserved. Whitespace is collapsed.
    """
    text = value.replace("\r", " ").replace("\n", " ")
    text = _TITLE_CUSTOM_EMOJI_RE.sub(r"\1", text)
    text = _TITLE_HEADING_PREFIX_RE.sub("", text)
    text = _TITLE_BLOCKQUOTE_PREFIX_RE.sub("", text)
    text = _TITLE_TASK_PREFIX_RE.sub("", text)
    text = _TITLE_LIST_PREFIX_RE.sub("", text)
    text = _TITLE_IMAGE_RE.sub(r"\1", text)
    text = _TITLE_LINK_RE.sub(r"\1", text)
    text = _TITLE_INLINE_TAG_RE.sub("", text)
    text = _TITLE_BOLD_STAR_RE.sub(r"\1", text)
    text = _TITLE_BOLD_UNDERSCORE_RE.sub(r"\1", text)
    text = _TITLE_STRIKE_RE.sub(r"\1", text)
    text = _TITLE_INLINE_CODE_RE.sub(r"\1", text)
    text = _TITLE_ITALIC_STAR_RE.sub(r"\1", text)
    text = _TITLE_ITALIC_UNDERSCORE_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_title(*candidates: str | None, max_length: int = 80) -> str:
    """Pick the first clean non-empty line from candidates and truncate."""
    for candidate in candidates:
        if not candidate:
            continue
        for line in str(candidate).splitlines():
            cleaned = _strip_title_markdown(line)
            if cleaned:
                return cleaned[:max_length]
    return ""


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _optional_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _optional_list(value: Any) -> list[Any] | None:
    return value if isinstance(value, list) else None


class NoteNotFoundError(Exception):
    pass


class FolderNotFoundError(Exception):
    pass


class ThumbnailPendingError(Exception):
    pass


class ThumbnailUnavailableError(Exception):
    pass


@dataclass(slots=True)
class UploadedContent:
    filename: str
    content_type: str | None
    data: bytes


class ContentService:
    def __init__(
        self,
        session: AsyncSession,
        storage_root: Path | None = None,
        storage_backend: StorageBackend | None = None,
    ) -> None:
        self.session = session
        self.content = ContentRepository(session)
        self.legacy_tags = TagRepository(session)
        self.tag_service = TagsService(session)
        self.taxonomy = TaxonomyService(session)
        self.file_uploads = FileUploadRepository(session)
        storage_root = storage_root or Path("data/content")
        storage_backend = storage_backend or build_storage_backend(
            get_settings(),
            local_root=storage_root,
        )
        self.storage = ContentStorage(storage_root, backend=storage_backend)
        self.storage_objects = StorageObjectRepository(session)
        self.outbox = EventOutboxRepository(session)
        self.snapshots = SnapshotService(session, self.storage.root, self.storage.backend)
        self.api_prefix = get_settings().api_prefix

    async def create_note(
        self,
        *,
        owner_user_id: str,
        media_type: str | None,
        text: str | None,
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
        file_upload_ids: list[str],
    ) -> NoteCardResponse:
        await self._cleanup_expired_uploads(owner_user_id)
        if file_upload_ids:
            uploads: list[ContentFileUpload] = []
            for upload_id in file_upload_ids:
                upload = await self.file_uploads.get_available_by_id(
                    owner_user_id=owner_user_id,
                    upload_id=upload_id,
                )
                if upload is None:
                    raise NoteNotFoundError
                uploads.append(upload)

            if text is not None and len(uploads) == 1:
                # Single file + text → composite note with both assets
                upload = uploads[0]
                card = await self._create_composite_note(
                    owner_user_id=owner_user_id,
                    uploaded=UploadedContent(
                        filename=upload.source_filename,
                        content_type=upload.mime_type,
                        data=self.storage.read_relative_file(upload.storage_path),
                    ),
                    text=text,
                    title=title,
                    folder_path=folder_path,
                    tag_names=tag_names,
                )
            else:
                card = await self._create_from_uploaded_files(
                    owner_user_id=owner_user_id,
                    files=[
                        UploadedContent(
                            filename=upload.source_filename,
                            content_type=upload.mime_type,
                            data=self.storage.read_relative_file(upload.storage_path),
                        )
                        for upload in uploads
                    ],
                    title=title,
                    folder_path=folder_path,
                    tag_names=tag_names,
                    object_id=None,
                )
            now = datetime.now(UTC)
            for upload in uploads:
                upload.consumed_at = now
            await self.session.commit()
            return card

        if media_type in (None, "text", "link") and text is not None:
            links, text_with_markdown_links = self._extract_links_from_text(text)
            logger.info(
                "content.note.link_extraction",
                owner_user_id=owner_user_id,
                media_type=media_type,
                link_count=len(links),
                has_remaining_text=bool(text_with_markdown_links),
                links=links,
            )
            if links:
                link_only_url = self._link_only_url(text)
                if link_only_url is not None and len(links) == 1:
                    return await self._create_link_note(
                        owner_user_id=owner_user_id,
                        url=link_only_url,
                        title=title,
                        folder_path=folder_path,
                        tag_names=tag_names,
                    )
                return await self._create_note_from_text_and_links(
                    owner_user_id=owner_user_id,
                    text=text_with_markdown_links,
                    title_source_text=text,
                    links=links,
                    title=title,
                    folder_path=folder_path,
                    tag_names=tag_names,
                )
            return await self._create_text_note(
                owner_user_id=owner_user_id,
                text=text,
                title=title,
                folder_path=folder_path,
                tag_names=tag_names,
            )

        raise NoteNotFoundError

    async def upload_files(
        self,
        *,
        owner_user_id: str,
        files: list[UploadedContent],
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
        create_or_attach_object: bool,
        object_id: str | None,
    ) -> NoteCardResponse | FileUploadResponse:
        await self._cleanup_expired_uploads(owner_user_id)
        logger.info(
            "content.upload.received",
            file_count=len(files),
            create_or_attach_object=create_or_attach_object,
            object_id=object_id,
            media_types=[self._media_type(file.filename, file.content_type) for file in files],
        )
        if create_or_attach_object:
            return await self._create_from_uploaded_files(
                owner_user_id=owner_user_id,
                files=files,
                title=title,
                folder_path=folder_path,
                tag_names=tag_names,
                object_id=object_id,
            )

        expires_at = datetime.now(UTC) + timedelta(hours=24)
        uploads: list[ContentFileUpload] = []
        for uploaded in files:
            upload = ContentFileUpload(
                owner_user_id=owner_user_id,
                source_filename=uploaded.filename,
                mime_type=uploaded.content_type,
                media_type=self._media_type(uploaded.filename, uploaded.content_type),
                size_bytes=len(uploaded.data),
                storage_path="pending",
                expires_at=expires_at,
            )
            self.file_uploads.add(upload)
            await self.session.flush()
            stored_file = self.storage.write_temp_file(
                owner_user_id=owner_user_id,
                upload_id=upload.id,
                filename=uploaded.filename,
                data=uploaded.data,
            )
            upload.storage_path = stored_file.relative_path
            upload.storage_backend = stored_file.storage_backend
            upload.bucket = stored_file.bucket
            upload.storage_key = stored_file.storage_key
            upload.storage_ref = stored_file.storage_ref
            upload.checksum = stored_file.checksum
            upload.size_bytes = stored_file.size_bytes
            self.storage_objects.add(
                self._stored_object_from_file(stored_file),
                owner_entity_type="content_file_upload",
                owner_entity_id=upload.id,
                metadata={"source_filename": uploaded.filename},
            )
            uploads.append(upload)

        await self.session.commit()
        return FileUploadResponse(
            files=[
                UploadedFileResponse(
                    id=upload.id,
                    source_filename=upload.source_filename,
                    media_type=upload.media_type,  # type: ignore[arg-type]
                    mime_type=upload.mime_type,
                    size_bytes=upload.size_bytes,
                    expires_at=upload.expires_at,
                )
                for upload in uploads
            ],
            object=None,
        )

    async def list_notes(
        self,
        *,
        owner_user_id: str,
        search: str | None,
        search_result_ids: list[str] | None = None,
        search_matches_by_object_id: dict[str, list[SearchContentMatch]] | None = None,
        include_local_search_matches: bool = False,
        tag_slugs: list[str],
        folder_path: str | None,
        sort: str,
    ) -> NoteListResponse:
        objects = await self.content.list_all(owner_user_id=owner_user_id)
        normalized_search = search.casefold().strip() if search else None
        search_rank = (
            {content_object_id: index for index, content_object_id in enumerate(search_result_ids)}
            if search_result_ids is not None
            else None
        )
        normalized_tags = {slugify(tag) for tag in tag_slugs}
        assignment_by_object_id = await self._current_assignment_map(owner_user_id)
        tags_by_object_id = await self.tag_service.list_active_tags_for_contents(
            owner_user_id=owner_user_id,
            content_object_ids=[content_object.id for content_object in objects],
        )
        items: list[ContentObject] = []
        seen_item_ids: set[str] = set()
        local_search_scores: dict[str, float] = {}

        for content_object in objects:
            assignment = assignment_by_object_id.get(content_object.id)
            local_search_score = (
                self._local_search_score(
                    content_object,
                    normalized_search,
                    active_tags=tags_by_object_id.get(content_object.id, []),
                    assignment=assignment,
                )
                if normalized_search
                else 0.0
            )
            if local_search_score > 0:
                local_search_scores[content_object.id] = local_search_score
            if (
                search_rank is not None
                and content_object.id not in search_rank
                and (not include_local_search_matches or local_search_score <= 0)
            ):
                continue
            if folder_path and (
                assignment is None
                or not self._path_matches_or_descends(
                    assignment.category_path_snapshot,
                    folder_path,
                )
            ):
                continue
            if normalized_tags and not normalized_tags.issubset(
                {tag.slug for tag in tags_by_object_id.get(content_object.id, [])},
            ):
                continue
            if normalized_search and search_rank is None:
                if content_object.kind == "collection":
                    for item in await self.content.list_collection_items(content_object.id):
                        child = item.content_object
                        if child.id in seen_item_ids:
                            continue
                        child_score = self._local_search_score(
                            child,
                            normalized_search,
                            active_tags=tags_by_object_id.get(child.id, []),
                            assignment=assignment_by_object_id.get(child.id),
                        )
                        if child_score > 0:
                            local_search_scores[child.id] = child_score
                            items.append(child)
                            seen_item_ids.add(child.id)
                    continue
                if local_search_score <= 0:
                    continue
                if content_object.id in seen_item_ids:
                    continue
                items.append(content_object)
                seen_item_ids.add(content_object.id)
                continue
            if (
                search_rank is None
                and content_object.kind != "collection"
                and content_object.collection_memberships
            ):
                continue
            items.append(content_object)

        if search_rank is not None:
            items.sort(
                key=lambda item: (
                    -local_search_scores.get(item.id, 0.0),
                    search_rank.get(item.id, 10**9),
                    -self._external_search_match_score(
                        item.id,
                        search_matches_by_object_id,
                    ),
                    item.sort_order if sort == "custom" else 0,
                    -item.created_at.timestamp(),
                )
            )
        elif sort == "custom":
            items.sort(key=lambda item: (item.sort_order, item.created_at))
        elif folder_path:
            items.sort(
                key=lambda item: (
                    assignment_by_object_id[item.id].category_path_snapshot != folder_path,
                    -item.created_at.timestamp(),
                )
            )
        else:
            items.sort(key=lambda item: item.created_at, reverse=True)

        return NoteListResponse(
            items=[
                await self._to_card(
                    item,
                    active_tags=tags_by_object_id.get(item.id, []),
                    search_matches=(
                        search_matches_by_object_id.get(item.id, [])
                        if search_matches_by_object_id is not None
                        else None
                    ),
                )
                for item in items
            ]
        )

    async def get_note(self, *, owner_user_id: str, slug: str) -> NoteCardResponse:
        return await self._to_card(await self._load_note(owner_user_id=owner_user_id, slug=slug))

    async def attach_source_metadata(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        source: dict[str, Any],
        content_asset_id: str | None = None,
    ) -> None:
        provider = source.get("provider")
        external_id = source.get("external_id")
        if not isinstance(provider, str) or not provider or not isinstance(external_id, str):
            return

        existing = await self.session.scalar(
            select(ContentSource).where(
                ContentSource.provider == provider,
                ContentSource.external_id == external_id,
                ContentSource.content_object_id == content_object_id,
            )
        )
        if existing is None:
            existing = ContentSource(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                content_asset_id=content_asset_id,
                provider=provider,
                provider_label=str(source.get("provider_label") or provider.title()),
                external_id=external_id,
            )
            self.session.add(existing)

        existing.content_asset_id = content_asset_id
        existing.provider_label = str(source.get("provider_label") or provider.title())
        existing.group_id = _optional_string(source.get("group_id"))
        existing.source_url = _optional_string(source.get("url"))
        existing.title = _optional_string(source.get("title"))
        existing.original_created_at = _optional_datetime(source.get("original_created_at"))
        existing.origin = _optional_dict(source.get("origin"))
        existing.author = _optional_dict(source.get("author"))
        existing.entities = _optional_list(source.get("entities"))
        existing.custom_emoji_ids = _optional_list(source.get("custom_emoji_ids"))
        existing.raw_payload = _optional_dict(source.get("raw_payload"))
        existing.source_metadata = _optional_dict(source.get("metadata"))
        await self.session.flush()

    async def list_trash(self, *, owner_user_id: str) -> NoteListResponse:
        objects = await self.content.list_deleted(owner_user_id=owner_user_id)
        tags_by_object_id = await self.tag_service.list_active_tags_for_contents(
            owner_user_id=owner_user_id,
            content_object_ids=[content_object.id for content_object in objects],
        )
        return NoteListResponse(
            items=[
                await self._to_card(item, active_tags=tags_by_object_id.get(item.id, []))
                for item in objects
                if item.kind == "collection" or not item.collection_memberships
            ]
        )

    async def restore_note(self, *, owner_user_id: str, slug: str) -> NoteCardResponse:
        content_object = await self.content.get_by_slug(
            owner_user_id=owner_user_id,
            slug=slug,
            include_deleted=True,
        )
        if content_object is None or content_object.deleted_at is None:
            raise NoteNotFoundError
        to_restore = await self._collect_objects_for_delete([content_object])
        for obj in to_restore.values():
            obj.deleted_at = None
            obj.delete_after = None
            self._enqueue_content_changed_event(obj, event_name="content.object.updated")
        await self.session.commit()
        await self.session.refresh(content_object)
        return await self._to_card(content_object)

    async def cleanup_expired_trash(self, *, owner_user_id: str) -> int:
        now = datetime.now(UTC)
        objects = [
            item
            for item in await self.content.list_deleted(owner_user_id=owner_user_id)
            if item.delete_after is not None and item.delete_after <= now
        ]
        to_delete = await self._collect_objects_for_delete(objects)
        if not to_delete:
            return 0
        await self._hard_delete_objects(to_delete)
        return len(to_delete)

    async def get_download_path(self, *, owner_user_id: str, slug: str) -> Path:
        content_object = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        return self.storage.build_archive(content_object)

    async def build_classification_input(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        text_excerpt_max_chars: int = 4000,
    ) -> ContentClassificationInput:
        content_object = await self.content.get_by_id(
            owner_user_id=owner_user_id,
            object_id=content_object_id,
        )
        if content_object is None:
            raise NoteNotFoundError
        text_excerpt = await self._classification_text_excerpt(
            content_object,
            max_chars=text_excerpt_max_chars,
        )
        url = (
            content_object.source_filename
            if content_object.media_type == "link"
            and content_object.source_filename is not None
            and self._plain_url(content_object.source_filename) is not None
            else None
        )
        object_source, _ = await self._source_metadata_for_object(content_object)
        return ContentClassificationInput(
            content_object_id=content_object.id,
            title=content_object.title,
            text_excerpt=text_excerpt,
            url=url,
            tags=[
                tag.slug
                for tag in sorted(
                    (
                        await self.tag_service.list_active_tags_for_contents(
                            owner_user_id=owner_user_id,
                            content_object_ids=[content_object.id],
                        )
                    ).get(content_object.id, []),
                    key=lambda tag: tag.name,
                )
            ],
            metadata={
                "kind": content_object.kind,
                "media_type": content_object.media_type,
                "source_filename": content_object.source_filename,
                "mime_type": content_object.mime_type,
                "size_bytes": content_object.size_bytes,
                "is_favorite": content_object.is_favorite,
                "content_created_at": content_object.created_at.isoformat(),
                "content_updated_at": content_object.updated_at.isoformat(),
                "content_source_provider": (object_source.provider if object_source else None),
                "source_original_created_at": (
                    object_source.original_created_at.isoformat()
                    if object_source and object_source.original_created_at
                    else None
                ),
                "source_kind": (
                    str(object_source.origin.get("type"))
                    if object_source and isinstance(object_source.origin, dict)
                    else None
                ),
                "source_title": (
                    str(
                        object_source.title
                        or (object_source.origin or {}).get("title")
                        or (object_source.origin or {}).get("name")
                        or (object_source.origin or {}).get("username")
                    )
                    if object_source
                    and (
                        object_source.title
                        or (object_source.origin or {}).get("title")
                        or (object_source.origin or {}).get("name")
                        or (object_source.origin or {}).get("username")
                    )
                    else None
                ),
                "telegram_chat_id": (
                    object_source.external_id.split(":", 1)[0]
                    if object_source and object_source.provider == "telegram"
                    else None
                ),
                "telegram_chat_type": (
                    self._telegram_chat_type(object_source.origin)
                    if object_source and object_source.provider == "telegram"
                    else None
                ),
                "telegram_author_id": (
                    str(object_source.author.get("id"))
                    if object_source
                    and object_source.provider == "telegram"
                    and isinstance(object_source.author, dict)
                    and object_source.author.get("id") is not None
                    else None
                ),
            },
            created_at=content_object.created_at,
            updated_at=content_object.updated_at,
        )

    async def get_asset_file(
        self, *, owner_user_id: str, slug: str, asset_id: str
    ) -> tuple[Path, str]:
        """Returns (absolute_path, mime_type) for the asset file."""
        content_object = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        asset = next((a for a in content_object.assets if a.id == asset_id), None)
        if asset is None:
            raise NoteNotFoundError
        path = self.storage.root / asset.storage_path
        if not path.exists():
            temp_file = NamedTemporaryFile(prefix=f"{asset.id}-", delete=False)
            temp_file.write(self.storage.backend.get_bytes(asset.storage_key or asset.storage_path))
            temp_file.close()
            path = Path(temp_file.name)
        mime = asset.mime_type or "application/octet-stream"
        return path, mime

    async def update_note(
        self,
        *,
        owner_user_id: str,
        slug: str,
        title: str | None,
        tag_names: list[str] | None,
    ) -> NoteCardResponse:
        content_object = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        if title is not None:
            cleaned_title = _normalize_title(title)
            if cleaned_title:
                content_object.title = cleaned_title
        if tag_names is not None:
            await self.tag_service.replace_manual_tags_for_content(
                owner_user_id=owner_user_id,
                content_object_id=content_object.id,
                tag_names=tag_names,
                assigned_by_user_id=owner_user_id,
                commit=False,
            )
            await self._sync_legacy_tags_for_content(
                owner_user_id=owner_user_id,
                content_object=content_object,
                tag_names=tag_names,
            )
        self._enqueue_content_changed_event(content_object, event_name="content.object.updated")
        await self.session.commit()
        loaded = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        return await self._to_card(loaded)

    async def set_favorite(
        self,
        *,
        owner_user_id: str,
        slug: str,
        is_favorite: bool,
    ) -> NoteCardResponse:
        content_object = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        content_object.is_favorite = is_favorite
        self._enqueue_content_changed_event(content_object, event_name="content.object.updated")
        await self.session.commit()
        loaded = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        return await self._to_card(loaded)

    async def reorder(
        self,
        *,
        owner_user_id: str,
        positions: dict[str, int],
    ) -> None:
        objects = await self.content.list_by_slugs(
            owner_user_id=owner_user_id,
            slugs=list(positions.keys()),
        )
        found_slugs = {content_object.slug for content_object in objects}
        if found_slugs != set(positions):
            raise NoteNotFoundError
        for content_object in objects:
            content_object.sort_order = positions[content_object.slug]
        await self.session.commit()

    async def merge_notes(
        self,
        *,
        owner_user_id: str,
        target_slug: str,
        source_slugs: list[str],
        title: str | None,
    ) -> NoteCardResponse:
        target = await self._load_note(owner_user_id=owner_user_id, slug=target_slug)
        unique_source_slugs = [slug for slug in dict.fromkeys(source_slugs) if slug != target_slug]
        sources = await self.content.list_by_slugs(
            owner_user_id=owner_user_id,
            slugs=unique_source_slugs,
        )
        if len(sources) != len(unique_source_slugs):
            raise NoteNotFoundError

        by_slug = {content_object.slug: content_object for content_object in sources}
        collection = await self._ensure_collection(target, title=title)
        target_assignment = await self.taxonomy.get_current_assignment(
            owner_user_id=owner_user_id,
            content_object_id=collection.id,
        )
        next_position = await self._next_collection_position(collection)
        for slug in unique_source_slugs:
            source = by_slug[slug]
            await self._assign_object_tree_to_category(source, target_assignment)
            existing_membership = await self.content.get_membership(source.id)
            if existing_membership is not None:
                existing_membership.collection = collection
                existing_membership.position = next_position
            else:
                self.content.add_collection_item(
                    ContentCollectionItem(
                        collection=collection,
                        content_object=source,
                        position=next_position,
                    ),
                )
            next_position += 10

        await self.session.commit()
        return await self._reload_write_manifest_and_card(
            owner_user_id=owner_user_id,
            slug=collection.slug,
        )

    async def remove_collection_items(
        self,
        *,
        owner_user_id: str,
        collection_slug: str,
        item_slugs: list[str],
    ) -> None:
        """Detach items from a collection.

        If only one item would remain after removal, the collection is collapsed:
        the child's assets are moved to the parent and the parent kind is updated
        to match the child, removing the collection wrapper.
        """
        collection = await self._load_note(owner_user_id=owner_user_id, slug=collection_slug)
        if collection.kind != "collection":
            raise NoteNotFoundError

        items = await self.content.list_collection_items(collection.id)
        slug_set = set(item_slugs)
        ids_to_remove_set = {item.id for item in items if item.content_object.slug in slug_set}
        remaining = [item for item in items if item.id not in ids_to_remove_set]

        if not ids_to_remove_set:
            return

        await self.session.execute(
            sql_delete(ContentCollectionItem).where(ContentCollectionItem.id.in_(ids_to_remove_set))
        )

        if len(remaining) == 1:
            child = remaining[0].content_object
            # Only collapse when child is a leaf note (simple/complex), not another collection
            if child.kind in ("simple", "complex"):
                child_id = child.id
                child_kind = child.kind
                child_media_type = child.media_type
                # Move child's assets to the parent collection object
                await self.session.execute(
                    sql_update(ContentAsset)
                    .where(ContentAsset.content_object_id == child_id)
                    .values(content_object_id=collection.id)
                )
                # Update parent to take the child's kind/media_type
                await self.session.execute(
                    sql_update(ContentObject)
                    .where(ContentObject.id == collection.id)
                    .values(kind=child_kind, media_type=child_media_type)
                )
                # Delete child — DB-level CASCADE removes the ContentCollectionItem link
                await self.session.execute(
                    sql_delete(ContentObject).where(ContentObject.id == child_id)
                )

        self._enqueue_content_changed_event(collection, event_name="content.object.updated")
        await self.session.commit()

    async def delete_notes(self, *, owner_user_id: str, slugs: list[str]) -> None:
        objects = await self.content.list_by_slugs(
            owner_user_id=owner_user_id,
            slugs=slugs,
        )
        to_delete = await self._collect_objects_for_delete(objects)
        taxonomy_settings = await self.taxonomy.get_user_settings(owner_user_id=owner_user_id)
        if taxonomy_settings.trash_enabled:
            now = datetime.now(UTC)
            delete_after = now + timedelta(days=taxonomy_settings.trash_retention_days)
            for obj in to_delete.values():
                obj.deleted_at = now
                obj.delete_after = delete_after
                self._enqueue_content_changed_event(obj, event_name="content.object.deleted")
            await self.session.commit()
            return

        await self._hard_delete_objects(to_delete)

    async def _collect_objects_for_delete(
        self,
        objects: list[ContentObject],
    ) -> dict[str, ContentObject]:
        to_delete: dict[str, ContentObject] = {}
        queue = list(objects)
        while queue:
            obj = queue.pop()
            if obj.id in to_delete:
                continue
            to_delete[obj.id] = obj
            if obj.kind == "collection":
                items = await self.content.list_collection_items(obj.id)
                queue.extend(item.content_object for item in items)
        return to_delete

    async def _hard_delete_objects(self, to_delete: dict[str, ContentObject]) -> None:
        for obj in to_delete.values():
            self._enqueue_content_changed_event(obj, event_name="content.object.deleted")
            self.storage.remove_directory(obj)

        if to_delete:
            await self.session.execute(
                sql_delete(ContentObject).where(ContentObject.id.in_(list(to_delete.keys())))
            )
        await self.session.commit()

    async def list_folders(self, *, owner_user_id: str) -> FolderTreeResponse:
        categories = await self.taxonomy.repository.list_categories(
            owner_user_id=owner_user_id,
            include_archived=False,
        )
        counts = await self._folder_counts(owner_user_id=owner_user_id)
        by_id: dict[str, FolderTreeItem] = {
            category.id: self._folder_tree_item(
                category,
                direct_count=counts.get(category.path, (0, 0))[0],
                total_count=counts.get(category.path, (0, 0))[1],
            )
            for category in categories
        }
        roots: list[FolderTreeItem] = []
        for category in categories:
            item = by_id[category.id]
            if category.parent_id and category.parent_id in by_id:
                by_id[category.parent_id].children.append(item)
            else:
                roots.append(item)
        return FolderTreeResponse(items=roots)

    async def get_folder_detail(
        self,
        *,
        owner_user_id: str,
        folder_path: str,
    ) -> FolderDetailResponse:
        category = await self.taxonomy.repository.get_category_by_path(
            owner_user_id=owner_user_id,
            path=folder_path,
            include_archived=False,
        )
        if category is None:
            raise FolderNotFoundError
        counts = await self._folder_counts(owner_user_id=owner_user_id)
        assignment_by_object_id = await self._current_assignment_map(owner_user_id)
        all_notes = await self.content.list_all(owner_user_id=owner_user_id)
        tags_by_object_id = await self.tag_service.list_active_tags_for_contents(
            owner_user_id=owner_user_id,
            content_object_ids=[note.id for note in all_notes],
        )
        folder_notes = [
            note
            for note in all_notes
            if self._is_visible_note(note)
            and assignment_by_object_id.get(note.id) is not None
            and self._path_matches_or_descends(
                assignment_by_object_id[note.id].category_path_snapshot,
                folder_path,
            )
        ]
        folder_notes.sort(
            key=lambda note: (
                assignment_by_object_id[note.id].category_path_snapshot != folder_path,
                -note.created_at.timestamp(),
            )
        )
        tag_counts: dict[str, tuple[Tag, int]] = {}
        for note in folder_notes:
            for tag in tags_by_object_id.get(note.id, []):
                _, count = tag_counts.get(tag.slug, (tag, 0))
                tag_counts[tag.slug] = (tag, count + 1)
        tags = sorted(
            tag_counts.values(),
            key=lambda item: (-item[1], item[0].name.casefold()),
        )
        return FolderDetailResponse(
            folder=self._folder_response(
                category,
                direct_count=counts.get(category.path, (0, 0))[0],
                total_count=counts.get(category.path, (0, 0))[1],
            ),
            tags=[self._tag_response(tag, count=count) for tag, count in tags],
            notes=[
                await self._to_card(note, active_tags=tags_by_object_id.get(note.id, []))
                for note in folder_notes
            ],
        )

    async def _create_text_note(
        self,
        *,
        owner_user_id: str,
        text: str,
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> NoteCardResponse:
        normalized_title = _normalize_title(title, text) or "Новая заметка"
        slug = await self._unique_slug(owner_user_id, normalized_title)
        sort_order = await self._next_root_sort_order(owner_user_id=owner_user_id)
        content_object_id = str(uuid4())
        asset_id = str(uuid4())
        stored_file = self.storage.write_text_object(
            content_object_id=content_object_id,
            asset_id=asset_id,
            title=normalized_title,
            text=text,
        )
        content_object = ContentObject(
            id=content_object_id,
            owner_user_id=owner_user_id,
            slug=slug,
            title=normalized_title,
            kind="simple",
            media_type="text",
            source_filename=stored_file.filename,
            mime_type="text/markdown",
            size_bytes=stored_file.size_bytes,
            storage_path=f"content-assets/{content_object_id}",
            sort_order=sort_order,
        )
        self.storage_objects.add(
            self._stored_object_from_file(stored_file),
            owner_entity_type="content_asset",
            owner_entity_id=asset_id,
            metadata={"role": "original", "source_filename": stored_file.filename},
        )
        content_object.assets.append(
            ContentAsset(
                id=asset_id,
                role="original",
                media_type="text",
                filename=stored_file.filename,
                mime_type="text/markdown",
                size_bytes=stored_file.size_bytes,
                storage_path=stored_file.relative_path,
                storage_backend=stored_file.storage_backend,
                bucket=stored_file.bucket,
                storage_key=stored_file.storage_key,
                storage_ref=stored_file.storage_ref,
                checksum=stored_file.checksum,
                text_content=text,
            ),
        )
        self.content.add(content_object)
        await self.session.flush()
        await self.tag_service.replace_manual_tags_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            tag_names=tag_names,
            assigned_by_user_id=owner_user_id,
            commit=False,
        )
        await self._sync_legacy_tags_for_content(
            owner_user_id=owner_user_id,
            content_object=content_object,
            tag_names=tag_names,
        )
        await self.taxonomy.assign_content_to_path(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            raw_path=folder_path,
            reasoning="Assigned from note folder path.",
            commit=False,
        )
        await self.session.commit()
        return await self._reload_write_manifest_and_card(owner_user_id=owner_user_id, slug=slug)

    async def _create_link_note(
        self,
        *,
        owner_user_id: str,
        url: str,
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> NoteCardResponse:
        normalized_title = await self._resolve_link_title(url=url, title=title)
        slug = await self._unique_slug(owner_user_id, normalized_title)
        sort_order = await self._next_root_sort_order(owner_user_id=owner_user_id)
        content_object_id = str(uuid4())
        asset_id = str(uuid4())
        logger.info(
            "content.note.create_link.started",
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            asset_id=asset_id,
            url=url,
        )
        stored_file = self.storage.write_binary_object(
            content_object_id=content_object_id,
            asset_id=asset_id,
            filename="link.url",
            data=f"{url}\n".encode(),
            content_type="text/uri-list",
        )
        content_object = ContentObject(
            id=content_object_id,
            owner_user_id=owner_user_id,
            slug=slug,
            title=normalized_title,
            kind="complex",
            media_type="link",
            source_filename=url,
            mime_type="text/uri-list",
            size_bytes=stored_file.size_bytes,
            storage_path=f"content-assets/{content_object_id}",
            sort_order=sort_order,
        )
        self.storage_objects.add(
            self._stored_object_from_file(stored_file),
            owner_entity_type="content_asset",
            owner_entity_id=asset_id,
            metadata={"role": "original", "source_url": url},
        )
        content_object.assets.append(
            ContentAsset(
                id=asset_id,
                role="original",
                media_type="link",
                filename=stored_file.filename,
                mime_type="text/uri-list",
                size_bytes=stored_file.size_bytes,
                storage_path=stored_file.relative_path,
                storage_backend=stored_file.storage_backend,
                bucket=stored_file.bucket,
                storage_key=stored_file.storage_key,
                storage_ref=stored_file.storage_ref,
                checksum=stored_file.checksum,
                text_content=url,
            ),
        )
        self.content.add(content_object)
        await self.session.flush()
        await self.tag_service.replace_manual_tags_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            tag_names=tag_names,
            assigned_by_user_id=owner_user_id,
            commit=False,
        )
        await self._sync_legacy_tags_for_content(
            owner_user_id=owner_user_id,
            content_object=content_object,
            tag_names=tag_names,
        )
        await self.taxonomy.assign_content_to_path(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            raw_path=folder_path,
            reasoning="Assigned from note folder path.",
            commit=False,
        )
        await self.session.commit()
        logger.info(
            "content.note.create_link.committed",
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            asset_ids=[asset.id for asset in content_object.assets],
        )
        return await self._reload_write_manifest_and_card(owner_user_id=owner_user_id, slug=slug)

    async def _create_note_from_text_and_links(
        self,
        *,
        owner_user_id: str,
        text: str,
        title_source_text: str,
        links: list[str],
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> NoteCardResponse:
        has_text = bool(text.strip())
        normalized_title = _normalize_title(title, title_source_text, self._link_title(links[0]))
        slug = await self._unique_slug(owner_user_id, normalized_title)
        sort_order = await self._next_root_sort_order(owner_user_id=owner_user_id)
        content_object_id = str(uuid4())
        logger.info(
            "content.note.create_text_links.started",
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            link_count=len(links),
            has_text=has_text,
            links=links,
        )

        first_link_data = f"{links[0]}\n".encode()
        content_object = ContentObject(
            id=content_object_id,
            owner_user_id=owner_user_id,
            slug=slug,
            title=normalized_title,
            kind="complex",
            media_type="link",
            source_filename=links[0],
            mime_type="text/uri-list",
            size_bytes=len(first_link_data),
            storage_path=f"content-assets/{content_object_id}",
            sort_order=sort_order,
        )

        for i, url in enumerate(links[:AUTO_LINK_SNAPSHOT_LIMIT], start=1):
            content_object.assets.append(
                self._create_link_asset(
                    content_object_id=content_object_id,
                    url=url,
                    index=i,
                ),
            )

        if has_text:
            text_asset_id = str(uuid4())
            stored_text = self.storage.write_text_object(
                content_object_id=content_object_id,
                asset_id=text_asset_id,
                title=normalized_title,
                text=text,
            )
            self.storage_objects.add(
                self._stored_object_from_file(stored_text),
                owner_entity_type="content_asset",
                owner_entity_id=text_asset_id,
                metadata={"role": "text", "source_filename": stored_text.filename},
            )
            content_object.assets.append(
                ContentAsset(
                    id=text_asset_id,
                    role="text",
                    media_type="text",
                    filename=stored_text.filename,
                    mime_type="text/markdown",
                    size_bytes=stored_text.size_bytes,
                    storage_path=stored_text.relative_path,
                    storage_backend=stored_text.storage_backend,
                    bucket=stored_text.bucket,
                    storage_key=stored_text.storage_key,
                    storage_ref=stored_text.storage_ref,
                    checksum=stored_text.checksum,
                    text_content=text,
                ),
            )

        self.content.add(content_object)
        await self.session.flush()
        await self.tag_service.replace_manual_tags_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            tag_names=tag_names,
            assigned_by_user_id=owner_user_id,
            commit=False,
        )
        await self._sync_legacy_tags_for_content(
            owner_user_id=owner_user_id,
            content_object=content_object,
            tag_names=tag_names,
        )
        await self.taxonomy.assign_content_to_path(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            raw_path=folder_path,
            reasoning="Assigned from note folder path.",
            commit=False,
        )
        await self.session.commit()
        logger.info(
            "content.note.create_text_links.committed",
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            asset_ids=[asset.id for asset in content_object.assets],
            asset_media_types=[asset.media_type for asset in content_object.assets],
        )
        return await self._reload_write_manifest_and_card(owner_user_id=owner_user_id, slug=slug)

    async def _create_composite_note(
        self,
        *,
        owner_user_id: str,
        uploaded: UploadedContent,
        text: str,
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> NoteCardResponse:
        return await self.create_composite_note_from_uploads(
            owner_user_id=owner_user_id,
            files=[uploaded],
            text=text,
            title=title,
            folder_path=folder_path,
            tag_names=tag_names,
        )

    async def create_composite_note_from_uploads(
        self,
        *,
        owner_user_id: str,
        files: list[UploadedContent],
        text: str | None,
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> NoteCardResponse:
        if not files and text is not None:
            return await self._create_text_note(
                owner_user_id=owner_user_id,
                text=text,
                title=title,
                folder_path=folder_path,
                tag_names=tag_names,
            )
        if not files:
            raise NoteNotFoundError

        first_file = files[0]
        file_media_type = self._media_type(first_file.filename, first_file.content_type)
        normalized_title = _normalize_title(title) if title is not None else _normalize_title(text)
        if not normalized_title and title is None:
            normalized_title = Path(first_file.filename).stem or "Telegram message"
        slug = await self._unique_slug(owner_user_id, normalized_title)
        sort_order = await self._next_root_sort_order(owner_user_id=owner_user_id)
        content_object_id = str(uuid4())
        content_object = ContentObject(
            id=content_object_id,
            owner_user_id=owner_user_id,
            slug=slug,
            title=normalized_title,
            kind="complex",
            media_type=file_media_type,
            source_filename=first_file.filename,
            mime_type=first_file.content_type,
            size_bytes=len(first_file.data),
            storage_path=f"content-assets/{content_object_id}",
            sort_order=sort_order,
        )

        if text:
            text_asset_id = str(uuid4())
            stored_text = self.storage.write_text_object(
                content_object_id=content_object_id,
                asset_id=text_asset_id,
                title=normalized_title,
                text=text,
            )
            self.storage_objects.add(
                self._stored_object_from_file(stored_text),
                owner_entity_type="content_asset",
                owner_entity_id=text_asset_id,
                metadata={"role": "text", "source_filename": stored_text.filename},
            )
            content_object.assets.append(
                ContentAsset(
                    id=text_asset_id,
                    role="text",
                    media_type="text",
                    filename=stored_text.filename,
                    mime_type="text/markdown",
                    size_bytes=stored_text.size_bytes,
                    storage_path=stored_text.relative_path,
                    storage_backend=stored_text.storage_backend,
                    bucket=stored_text.bucket,
                    storage_key=stored_text.storage_key,
                    storage_ref=stored_text.storage_ref,
                    checksum=stored_text.checksum,
                    text_content=text,
                ),
            )

        for uploaded in files:
            file_asset_id = str(uuid4())
            stored_file = self.storage.write_binary_object(
                content_object_id=content_object_id,
                asset_id=file_asset_id,
                filename=uploaded.filename,
                data=uploaded.data,
                content_type=uploaded.content_type,
            )
            media_type = self._media_type(uploaded.filename, uploaded.content_type)
            image_width, image_height = (
                self._image_dimensions(uploaded) if media_type == "image" else (None, None)
            )
            self.storage_objects.add(
                self._stored_object_from_file(stored_file),
                owner_entity_type="content_asset",
                owner_entity_id=file_asset_id,
                metadata={"role": "original", "source_filename": uploaded.filename},
            )
            content_object.assets.append(
                ContentAsset(
                    id=file_asset_id,
                    role="original",
                    media_type=media_type,
                    filename=stored_file.filename,
                    mime_type=uploaded.content_type,
                    size_bytes=stored_file.size_bytes,
                    storage_path=stored_file.relative_path,
                    storage_backend=stored_file.storage_backend,
                    bucket=stored_file.bucket,
                    storage_key=stored_file.storage_key,
                    storage_ref=stored_file.storage_ref,
                    checksum=stored_file.checksum,
                    image_width=image_width,
                    image_height=image_height,
                ),
            )
        self.content.add(content_object)
        await self.session.flush()
        await self.tag_service.replace_manual_tags_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            tag_names=tag_names,
            assigned_by_user_id=owner_user_id,
            commit=False,
        )
        await self._sync_legacy_tags_for_content(
            owner_user_id=owner_user_id,
            content_object=content_object,
            tag_names=tag_names,
        )
        await self.taxonomy.assign_content_to_path(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            raw_path=folder_path,
            reasoning="Assigned from note folder path.",
            commit=False,
        )
        await self.session.commit()
        return await self._reload_write_manifest_and_card(owner_user_id=owner_user_id, slug=slug)

    def _create_link_asset(self, *, content_object_id: str, url: str, index: int) -> ContentAsset:
        asset_id = str(uuid4())
        filename = f"link-{index}.url"
        stored_file = self.storage.write_binary_object(
            content_object_id=content_object_id,
            asset_id=asset_id,
            filename=filename,
            data=f"{url}\n".encode(),
            content_type="text/uri-list",
        )
        self.storage_objects.add(
            self._stored_object_from_file(stored_file),
            owner_entity_type="content_asset",
            owner_entity_id=asset_id,
            metadata={"role": "original", "source_url": url},
        )
        return ContentAsset(
            id=asset_id,
            role="original",
            media_type="link",
            filename=filename,
            mime_type="text/uri-list",
            size_bytes=stored_file.size_bytes,
            storage_path=stored_file.relative_path,
            storage_backend=stored_file.storage_backend,
            bucket=stored_file.bucket,
            storage_key=stored_file.storage_key,
            storage_ref=stored_file.storage_ref,
            checksum=stored_file.checksum,
            text_content=url,
        )

    async def _create_from_uploaded_files(
        self,
        *,
        owner_user_id: str,
        files: list[UploadedContent],
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
        object_id: str | None,
    ) -> NoteCardResponse:
        existing = (
            await self.content.get_by_id(owner_user_id=owner_user_id, object_id=object_id)
            if object_id is not None
            else None
        )
        if existing is not None:
            collection = await self._ensure_collection(existing, title=title)
            next_position = await self._next_collection_position(collection)
            collection_assignment = await self.taxonomy.get_current_assignment(
                owner_user_id=owner_user_id,
                content_object_id=collection.id,
            )
            for uploaded in files:
                child = await self._create_uploaded_object(
                    owner_user_id=owner_user_id,
                    uploaded=uploaded,
                    folder_path=(
                        collection_assignment.category_path_snapshot
                        if collection_assignment is not None
                        else folder_path
                    ),
                    tag_names=tag_names,
                )
                self.content.add_collection_item(
                    ContentCollectionItem(
                        collection=collection,
                        content_object=child,
                        position=next_position,
                    ),
                )
                next_position += 10
            await self.session.commit()
            return await self._reload_write_manifest_and_card(
                owner_user_id=owner_user_id,
                slug=collection.slug,
            )

        if len(files) == 1:
            content_object = await self._create_uploaded_object(
                owner_user_id=owner_user_id,
                uploaded=files[0],
                folder_path=folder_path,
                tag_names=tag_names,
                object_id=object_id,
                title=title,
            )
            await self.session.commit()
            return await self._reload_write_manifest_and_card(
                owner_user_id=owner_user_id,
                slug=content_object.slug,
            )

        collection = await self._create_collection(
            owner_user_id=owner_user_id,
            title=_normalize_title(title) or "Imported collection",
            folder_path=folder_path,
            tag_names=tag_names,
            object_id=object_id,
        )
        for position, uploaded in enumerate(files, start=10):
            child = await self._create_uploaded_object(
                owner_user_id=owner_user_id,
                uploaded=uploaded,
                folder_path=folder_path,
                tag_names=tag_names,
            )
            self.content.add_collection_item(
                ContentCollectionItem(
                    collection=collection,
                    content_object=child,
                    position=position,
                ),
            )
        await self.session.commit()
        return await self._reload_write_manifest_and_card(
            owner_user_id=owner_user_id,
            slug=collection.slug,
        )

    async def _create_uploaded_object(
        self,
        *,
        owner_user_id: str,
        uploaded: UploadedContent,
        folder_path: str | None,
        tag_names: list[str],
        object_id: str | None = None,
        title: str | None = None,
    ) -> ContentObject:
        media_type = self._media_type(uploaded.filename, uploaded.content_type)
        kind = "complex" if media_type == "document" else "simple"
        normalized_title = _normalize_title(title) if title is not None else uploaded.filename
        slug = await self._unique_slug(
            owner_user_id,
            Path(uploaded.filename).stem or normalized_title or "uploaded-file",
        )
        sort_order = await self._next_root_sort_order(owner_user_id=owner_user_id)
        content_object_id = object_id or str(uuid4())
        asset_id = str(uuid4())
        stored_file = self.storage.write_binary_object(
            content_object_id=content_object_id,
            asset_id=asset_id,
            filename=uploaded.filename,
            data=uploaded.data,
            content_type=uploaded.content_type,
        )
        text_content = self._decode_text(uploaded.data) if media_type == "text" else None
        image_width, image_height = (
            self._image_dimensions(uploaded) if media_type == "image" else (None, None)
        )
        content_object = ContentObject(
            id=content_object_id,
            owner_user_id=owner_user_id,
            slug=slug,
            title=normalized_title,
            kind=kind,
            media_type=media_type,
            source_filename=stored_file.filename,
            mime_type=uploaded.content_type,
            size_bytes=stored_file.size_bytes,
            storage_path=f"content-assets/{content_object_id}",
            sort_order=sort_order,
        )
        self.storage_objects.add(
            self._stored_object_from_file(stored_file),
            owner_entity_type="content_asset",
            owner_entity_id=asset_id,
            metadata={"role": "original", "source_filename": uploaded.filename},
        )
        content_object.assets.append(
            ContentAsset(
                id=asset_id,
                role="original",
                media_type=media_type,
                filename=stored_file.filename,
                mime_type=uploaded.content_type,
                size_bytes=stored_file.size_bytes,
                storage_path=stored_file.relative_path,
                storage_backend=stored_file.storage_backend,
                bucket=stored_file.bucket,
                storage_key=stored_file.storage_key,
                storage_ref=stored_file.storage_ref,
                checksum=stored_file.checksum,
                text_content=text_content,
                image_width=image_width,
                image_height=image_height,
            ),
        )
        self.content.add(content_object)
        await self.session.flush()
        await self.tag_service.replace_manual_tags_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            tag_names=tag_names,
            assigned_by_user_id=owner_user_id,
            commit=False,
        )
        await self._sync_legacy_tags_for_content(
            owner_user_id=owner_user_id,
            content_object=content_object,
            tag_names=tag_names,
        )
        await self.taxonomy.assign_content_to_path(
            owner_user_id=owner_user_id,
            content_object_id=content_object.id,
            raw_path=folder_path,
            reasoning="Assigned from note folder path.",
            commit=False,
        )
        return content_object

    @staticmethod
    def _image_dimensions(uploaded: UploadedContent) -> tuple[int | None, int | None]:
        dimensions = ContentService._image_dimensions_from_header(uploaded.data)
        if dimensions is not None:
            return dimensions

        try:
            fitz: Any = importlib.import_module("fitz")
            doc: Any = fitz.open(
                stream=uploaded.data, filetype=ContentService._image_filetype(uploaded)
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "content.image_dimensions_unavailable",
                filename=uploaded.filename,
                content_type=uploaded.content_type,
                exc_info=True,
            )
            return None, None

        try:
            if doc.page_count == 0:
                return None, None
            try:
                page: Any = doc[0]
                width = int(page.rect.width)
                height = int(page.rect.height)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "content.image_dimensions_unavailable",
                    filename=uploaded.filename,
                    content_type=uploaded.content_type,
                    exc_info=True,
                )
                return None, None
            if width <= 0 or height <= 0:
                return None, None
            return width, height
        finally:
            doc.close()

    @staticmethod
    def _image_dimensions_from_header(data: bytes) -> tuple[int, int] | None:
        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            return (width, height) if width > 0 and height > 0 else None

        if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
            width = int.from_bytes(data[6:8], "little")
            height = int.from_bytes(data[8:10], "little")
            return (width, height) if width > 0 and height > 0 else None

        if data.startswith(b"RIFF") and len(data) >= 30 and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8 " and len(data) >= 30:
                width = int.from_bytes(data[26:28], "little") & 0x3FFF
                height = int.from_bytes(data[28:30], "little") & 0x3FFF
                return (width, height) if width > 0 and height > 0 else None
            if data[12:16] == b"VP8L" and len(data) >= 25:
                bits = int.from_bytes(data[21:25], "little")
                width = (bits & 0x3FFF) + 1
                height = ((bits >> 14) & 0x3FFF) + 1
                return (width, height) if width > 0 and height > 0 else None
            if data[12:16] == b"VP8X" and len(data) >= 30:
                width = int.from_bytes(data[24:27], "little") + 1
                height = int.from_bytes(data[27:30], "little") + 1
                return (width, height) if width > 0 and height > 0 else None

        if data.startswith(b"\xff\xd8"):
            index = 2
            while index + 9 < len(data):
                if data[index] != 0xFF:
                    index += 1
                    continue
                marker = data[index + 1]
                index += 2
                while marker == 0xFF and index < len(data):
                    marker = data[index]
                    index += 1
                if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                    continue
                if index + 2 > len(data):
                    return None
                segment_length = int.from_bytes(data[index : index + 2], "big")
                if segment_length < 2 or index + segment_length > len(data):
                    return None
                if marker in {
                    0xC0,
                    0xC1,
                    0xC2,
                    0xC3,
                    0xC5,
                    0xC6,
                    0xC7,
                    0xC9,
                    0xCA,
                    0xCB,
                    0xCD,
                    0xCE,
                    0xCF,
                }:
                    height = int.from_bytes(data[index + 3 : index + 5], "big")
                    width = int.from_bytes(data[index + 5 : index + 7], "big")
                    return (width, height) if width > 0 and height > 0 else None
                index += segment_length

        return None

    @staticmethod
    def _image_filetype(uploaded: UploadedContent) -> str:
        if uploaded.content_type and uploaded.content_type.startswith("image/"):
            return uploaded.content_type.removeprefix("image/")
        suffix = Path(uploaded.filename).suffix.lower().removeprefix(".")
        return "jpeg" if suffix == "jpg" else suffix

    async def _create_collection(
        self,
        *,
        owner_user_id: str,
        title: str,
        folder_path: str | None,
        tag_names: list[str],
        object_id: str | None = None,
        slug: str | None = None,
    ) -> ContentObject:
        normalized_title = _normalize_title(title) or "Imported collection"
        normalized_slug = slug or await self._unique_slug(owner_user_id, normalized_title)
        sort_order = await self._next_root_sort_order(owner_user_id=owner_user_id)
        content_object_id = object_id or str(uuid4())
        collection = ContentObject(
            id=content_object_id,
            owner_user_id=owner_user_id,
            slug=normalized_slug,
            title=normalized_title,
            kind="collection",
            media_type=None,
            storage_path=f"content-assets/{content_object_id}",
            sort_order=sort_order,
        )
        self.content.add(collection)
        await self.session.flush()
        await self.tag_service.replace_manual_tags_for_content(
            owner_user_id=owner_user_id,
            content_object_id=collection.id,
            tag_names=tag_names,
            assigned_by_user_id=owner_user_id,
            commit=False,
        )
        await self._sync_legacy_tags_for_content(
            owner_user_id=owner_user_id,
            content_object=collection,
            tag_names=tag_names,
        )
        await self.taxonomy.assign_content_to_path(
            owner_user_id=owner_user_id,
            content_object_id=collection.id,
            raw_path=folder_path,
            reasoning="Assigned from note folder path.",
            commit=False,
        )
        return collection

    async def _ensure_collection(
        self,
        content_object: ContentObject,
        *,
        title: str | None,
    ) -> ContentObject:
        if content_object.kind == "collection":
            if title:
                content_object.title = _normalize_title(title) or content_object.title
            return content_object

        child_slug = await self._unique_slug(
            content_object.owner_user_id,
            f"{content_object.slug}-item",
        )
        current_assignment = await self.taxonomy.get_current_assignment(
            owner_user_id=content_object.owner_user_id,
            content_object_id=content_object.id,
        )
        child = ContentObject(
            id=str(uuid4()),
            owner_user_id=content_object.owner_user_id,
            slug=child_slug,
            title=content_object.title,
            kind=content_object.kind,
            media_type=content_object.media_type,
            source_filename=content_object.source_filename,
            mime_type=content_object.mime_type,
            size_bytes=content_object.size_bytes,
            storage_path=content_object.storage_path,
            sort_order=content_object.sort_order,
            tags=list(content_object.tags),
        )
        for asset in list(content_object.assets):
            asset.content_object = child

        content_object.title = title or content_object.title
        content_object.kind = "collection"
        content_object.media_type = None
        content_object.source_filename = None
        content_object.mime_type = None
        content_object.size_bytes = None
        content_object.storage_path = f"content-assets/{content_object.id}"
        self.content.add(child)
        await self.session.flush()
        inherited_tags = (
            await self.tag_service.list_active_tags_for_contents(
                owner_user_id=content_object.owner_user_id,
                content_object_ids=[content_object.id],
            )
        ).get(content_object.id, [])
        for tag in inherited_tags:
            await self.tag_service.assign_tag_to_content(
                owner_user_id=content_object.owner_user_id,
                content_object_id=child.id,
                tag_id=tag.id,
                assigned_by_user_id=content_object.owner_user_id,
                reasoning="Inherited from collection source object.",
                commit=False,
            )
        if current_assignment is not None:
            await self.taxonomy.create_manual_assignment(
                owner_user_id=content_object.owner_user_id,
                content_object_id=child.id,
                category_id=current_assignment.category_id,
                reasoning="Inherited from collection source object.",
                commit=False,
            )
        self.content.add_collection_item(
            ContentCollectionItem(collection=content_object, content_object=child, position=10),
        )
        return content_object

    async def _next_collection_position(self, collection: ContentObject) -> int:
        current_items = await self.content.list_collection_items(collection.id)
        return max((item.position for item in current_items), default=0) + 10

    async def _next_root_sort_order(self, *, owner_user_id: str) -> int:
        return await self.content.get_min_sort_order(owner_user_id=owner_user_id) - 10

    async def _assign_object_tree_to_category(
        self,
        content_object: ContentObject,
        assignment: TaxonomyContentAssignment | None,
    ) -> None:
        if assignment is not None:
            await self.taxonomy.create_manual_assignment(
                owner_user_id=content_object.owner_user_id,
                content_object_id=content_object.id,
                category_id=assignment.category_id,
                reasoning="Assigned during content merge.",
                commit=False,
            )
        if content_object.kind != "collection":
            return
        for item in await self.content.list_collection_items(content_object.id):
            await self._assign_object_tree_to_category(item.content_object, assignment)

    async def _reload_write_manifest_and_card(
        self,
        *,
        owner_user_id: str,
        slug: str,
    ) -> NoteCardResponse:
        loaded = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        items = [
            item.content_object for item in await self.content.list_collection_items(loaded.id)
        ]
        assignment_by_object_id = await self._current_assignment_map(owner_user_id)
        tags_by_object_id = await self.tag_service.list_active_tags_for_contents(
            owner_user_id=owner_user_id,
            content_object_ids=[loaded.id, *(item.id for item in items)],
        )
        self.storage.write_manifest(
            content_object_id=loaded.id,
            manifest=self._manifest(
                loaded,
                items=items,
                assignment=assignment_by_object_id.get(loaded.id),
                tags=tags_by_object_id.get(loaded.id, []),
            ),
        )
        if loaded.kind == "collection":
            for item in items:
                self.storage.write_manifest(
                    content_object_id=item.id,
                    manifest=self._manifest(
                        item,
                        items=[],
                        assignment=assignment_by_object_id.get(item.id),
                        tags=tags_by_object_id.get(item.id, []),
                    ),
                )
        all_objects = [loaded, *items] if loaded.kind == "collection" else [loaded]
        for obj in all_objects:
            envelope = self._enqueue_content_changed_event(
                obj,
                event_name="content.object.created",
            )
            logger.info(
                "content.note.enqueue_automatic_processing",
                owner_user_id=owner_user_id,
                content_object_id=obj.id,
                kind=obj.kind,
                media_type=obj.media_type,
                asset_ids=[asset.id for asset in obj.assets],
                asset_media_types=[asset.media_type for asset in obj.assets],
                event_id=envelope.event_id,
            )
            await self._enqueue_automatic_processing(obj, envelope=envelope)
        await self.session.commit()
        return await self._to_card(loaded)

    async def decide_deferred_link_snapshots(
        self,
        *,
        owner_user_id: str,
        slug: str,
        decision: str,
    ) -> NoteCardResponse:
        content_object = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        if decision == "reject":
            await self._set_link_snapshot_decision(
                content_object=content_object,
                status="rejected",
            )
            await self.session.commit()
            return await self._to_card(content_object)

        remaining = self._remaining_text_link_urls(content_object)
        existing_link_count = len(self._link_asset_urls(content_object))
        for index, url in enumerate(remaining, start=existing_link_count + 1):
            content_object.assets.append(
                self._create_link_asset(
                    content_object_id=content_object.id,
                    url=url,
                    index=index,
                ),
            )
        content_object.updated_at = datetime.now(UTC)
        await self.session.flush()
        await self._set_link_snapshot_decision(
            content_object=content_object,
            status="accepted",
        )
        await self._write_object_manifest(content_object)
        if remaining:
            envelope = self._enqueue_content_changed_event(
                content_object,
                event_name="content.object.updated",
            )
            await self._enqueue_automatic_processing(content_object, envelope=envelope)
        await self.session.commit()
        return await self._to_card(content_object)

    async def _write_object_manifest(self, content_object: ContentObject) -> None:
        assignment_by_object_id = await self._current_assignment_map(content_object.owner_user_id)
        tags_by_object_id = await self.tag_service.list_active_tags_for_contents(
            owner_user_id=content_object.owner_user_id,
            content_object_ids=[content_object.id],
        )
        self.storage.write_manifest(
            content_object_id=content_object.id,
            manifest=self._manifest(
                content_object,
                items=[],
                assignment=assignment_by_object_id.get(content_object.id),
                tags=tags_by_object_id.get(content_object.id, []),
            ),
        )

    async def get_asset_thumbnail(
        self, *, owner_user_id: str, slug: str, asset_id: str
    ) -> tuple[Path, str]:
        """Returns path and MIME type for a generated thumbnail artifact."""
        content_object = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        asset = next((a for a in content_object.assets if a.id == asset_id), None)
        if asset is None:
            raise NoteNotFoundError
        thumbnail = await self.snapshots.get_thumbnail_path(source_asset_id=asset.id)
        if thumbnail is None:
            if await self.snapshots.is_thumbnail_unavailable(source_asset_id=asset.id):
                raise ThumbnailUnavailableError
            raise ThumbnailPendingError
        path, mime_type = thumbnail
        if not path.exists():
            raise ThumbnailPendingError
        return path, mime_type

    def _enqueue_content_changed_event(
        self,
        content_object: ContentObject,
        *,
        event_name: str,
    ) -> EventEnvelope:
        envelope = EventEnvelope.new(
            event_name=event_name,  # type: ignore[arg-type]
            entity_id=content_object.id,
            correlation_id=str(uuid4()),
            user_id=content_object.owner_user_id,
            payload=ContentObjectChangedPayload(
                content_object_id=content_object.id,
                asset_ids=[asset.id for asset in content_object.assets],
                storage_refs=[
                    asset.storage_ref
                    for asset in content_object.assets
                    if asset.storage_ref is not None
                ],
                metadata={
                    "kind": content_object.kind,
                    "media_type": content_object.media_type,
                },
            ),
        )
        self.outbox.add(envelope, routing_key=event_name)
        return envelope

    async def _enqueue_automatic_processing(
        self,
        content_object: ContentObject,
        *,
        envelope: EventEnvelope,
    ) -> None:
        if envelope.event_name not in {
            "content.object.created",
            "content.object.updated",
        }:
            return
        await self.snapshots.enqueue_for_content_object(
            content_object,
            correlation_id=envelope.correlation_id,
            source_event_id=envelope.event_id,
        )

    @staticmethod
    def _stored_object_from_file(stored_file: StoredFile) -> StoredObject:
        return StoredObject(
            storage_backend=stored_file.storage_backend,
            bucket=stored_file.bucket,
            storage_key=stored_file.storage_key,
            storage_ref=stored_file.storage_ref,
            content_type=stored_file.content_type,
            size_bytes=stored_file.size_bytes,
            checksum=stored_file.checksum,
        )

    async def _cleanup_expired_uploads(self, owner_user_id: str) -> None:
        expired_uploads = await self.file_uploads.list_expired(
            owner_user_id=owner_user_id,
            now=datetime.now(UTC),
        )
        for upload in expired_uploads:
            self.storage.remove_relative_file_parent(upload.storage_path)
            await self.session.delete(upload)
        if expired_uploads:
            await self.session.flush()

    async def _sync_legacy_tags_for_content(
        self,
        *,
        owner_user_id: str,
        content_object: ContentObject,
        tag_names: list[str],
    ) -> None:
        # Compatibility mirror for deprecated content_tags/content_object_tags schema artifacts.
        legacy_tags: list[LegacyContentTag] = []
        seen: set[str] = set()
        for raw_name in tag_names:
            name = raw_name.strip()
            if not name:
                continue
            slug = slugify(name)
            if slug in seen:
                continue
            seen.add(slug)
            legacy_tags.append(
                await self.legacy_tags.get_or_create(
                    owner_user_id=owner_user_id,
                    name=name,
                    slug=slug,
                )
            )
        await self.session.execute(
            sql_delete(ContentObjectTag).where(
                ContentObjectTag.content_object_id == content_object.id
            )
        )
        for tag in legacy_tags:
            self.session.add(ContentObjectTag(content_object_id=content_object.id, tag_id=tag.id))
        await self.session.flush()

    async def _unique_slug(self, owner_user_id: str, title: str) -> str:
        base = slugify(title)
        await self.content.lock_slug_base(owner_user_id=owner_user_id, slug_base=base)
        candidate = base
        counter = 2
        while await self.content.slug_exists(owner_user_id=owner_user_id, slug=candidate):
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    async def _load_note(self, *, owner_user_id: str, slug: str) -> ContentObject:
        ref = slug.strip()
        object_id = _note_path_ref_as_uuid(ref)
        content_object: ContentObject | None = None
        if object_id is not None:
            content_object = await self.content.get_by_id(
                owner_user_id=owner_user_id,
                object_id=object_id,
            )
            if content_object is None:
                content_object = await self.content.get_by_asset_id(
                    owner_user_id=owner_user_id,
                    asset_id=object_id,
                )
        if content_object is None:
            content_object = await self.content.get_by_slug(
                owner_user_id=owner_user_id,
                slug=ref,
            )
        if content_object is None:
            raise NoteNotFoundError
        return content_object

    async def _to_card(
        self,
        content_object: ContentObject,
        *,
        active_tags: list[Tag] | None = None,
        search_matches: list[SearchContentMatch] | None = None,
    ) -> NoteCardResponse:
        collection_parent = None
        if content_object.collection_memberships:
            collection = content_object.collection_memberships[0].collection
            collection_parent = CollectionParentResponse(
                id=collection.id,
                slug=collection.slug,
                title=collection.title,
            )
        items = []
        if content_object.kind == "collection":
            collection_items = await self.content.list_collection_items(content_object.id)
            items = [await self._to_card(item.content_object) for item in collection_items]
        if active_tags is None:
            active_tags = (
                await self.tag_service.list_active_tags_for_contents(
                    owner_user_id=content_object.owner_user_id,
                    content_object_ids=[content_object.id],
                )
            ).get(content_object.id, [])
        deferred_link_snapshots = await self._deferred_link_snapshots_for_object(content_object)
        current_assignment = await self.taxonomy.get_current_assignment(
            owner_user_id=content_object.owner_user_id,
            content_object_id=content_object.id,
        )
        object_source, asset_sources = await self._source_metadata_for_object(content_object)
        asset_responses: list[NoteAssetResponse] = []
        for asset in content_object.assets:
            asset_url = f"{self.api_prefix}/notes/{content_object.slug}/asset/{asset.id}"
            artifact_refs = await self.snapshots.get_asset_artifact_references(
                source_asset_id=asset.id
            )
            thumbnail = artifact_refs.get("thumbnail")
            thumbnail_text = (
                await self.snapshots.get_thumbnail_text(source_asset_id=asset.id)
                if "thumbnail_text" in artifact_refs
                else None
            )
            markdown = artifact_refs.get("markdown")
            pdf = artifact_refs.get("pdf")
            html = artifact_refs.get("webpage_html")
            is_text_asset = asset.media_type == "text"
            snapshot_views = self._snapshot_views_for_asset(
                asset=asset,
                asset_url=asset_url,
                markdown=markdown,
                pdf=pdf,
                html=html,
            )
            logger.info(
                "content.note.asset_artifact_refs",
                content_object_id=content_object.id,
                slug=content_object.slug,
                asset_id=asset.id,
                asset_media_type=asset.media_type,
                artifact_types=sorted(artifact_refs.keys()),
                has_html_url=html is not None,
                html_url=html.url if html is not None else None,
                snapshot_view_kinds=[view.kind for view in snapshot_views],
            )
            text_body = asset.text_content
            if asset.media_type == "text":
                from_file = self._read_text_asset_user_body(asset)
                if from_file is not None:
                    text_body = from_file
            asset_responses.append(
                NoteAssetResponse(
                    id=asset.id,
                    role=asset.role,
                    media_type=asset.media_type,  # type: ignore[arg-type]
                    filename=asset.filename,
                    mime_type=asset.mime_type,
                    size_bytes=asset.size_bytes,
                    url=asset_url,
                    text_content=text_body,
                    thumbnail_url=(
                        f"{self.api_prefix}/notes/{content_object.slug}/asset/{asset.id}/thumbnail"
                        if thumbnail is not None and not is_text_asset
                        else None
                    ),
                    thumbnail_text=thumbnail_text if not is_text_asset else None,
                    markdown_url=(
                        markdown.url
                        if markdown is not None
                        else (
                            asset_url
                            if self._is_markdown_asset(asset) and not is_text_asset
                            else None
                        )
                    ),
                    pdf_url=(
                        pdf.url
                        if pdf is not None
                        else asset_url if self._is_pdf_asset(asset) else None
                    ),
                    html_url=html.url if html is not None else None,
                    snapshot_views=snapshot_views,
                    image_width=asset.image_width,
                    image_height=asset.image_height,
                    source=asset_sources.get(asset.id) or object_source,
                )
            )
        return NoteCardResponse(
            id=content_object.id,
            slug=content_object.slug,
            kind=content_object.kind,  # type: ignore[arg-type]
            media_type=content_object.media_type,  # type: ignore[arg-type]
            title=content_object.title,
            source_filename=content_object.source_filename,
            taxonomy_category=self._taxonomy_category_response_from_assignment(current_assignment),
            tags=[self._tag_response(tag) for tag in active_tags],
            is_favorite=content_object.is_favorite,
            sort_order=content_object.sort_order,
            created_at=content_object.created_at,
            updated_at=content_object.updated_at,
            download_url=f"{self.api_prefix}/notes/{content_object.slug}/download",
            collection=collection_parent,
            source=object_source,
            deferred_link_snapshots=deferred_link_snapshots,
            search_matches=search_matches or [],
            assets=asset_responses,
            items=items,
        )

    async def _deferred_link_snapshots_for_object(
        self,
        content_object: ContentObject,
    ) -> DeferredLinkSnapshotsResponse | None:
        if content_object.media_type != "link":
            return None
        decision = await self._get_link_snapshot_decision(content_object.id)
        if decision is not None:
            return None

        expires_at = content_object.created_at + DEFERRED_LINK_SNAPSHOT_TTL
        if datetime.now(UTC) >= expires_at:
            return None

        text_links = self._text_link_urls(content_object)
        if len(text_links) <= AUTO_LINK_SNAPSHOT_LIMIT:
            return None

        remaining = self._remaining_text_link_urls(content_object)
        if not remaining:
            return None

        processed_links = len(
            [url for url in text_links if url in set(self._link_asset_urls(content_object))]
        )
        return DeferredLinkSnapshotsResponse(
            total_links=len(text_links),
            processed_links=processed_links,
            remaining_links=len(remaining),
            expires_at=expires_at,
            status="pending",
        )

    async def _get_link_snapshot_decision(
        self,
        content_object_id: str,
    ) -> ContentLinkSnapshotDecision | None:
        return await self.session.scalar(
            select(ContentLinkSnapshotDecision).where(
                ContentLinkSnapshotDecision.content_object_id == content_object_id
            )
        )

    async def _set_link_snapshot_decision(
        self,
        *,
        content_object: ContentObject,
        status: str,
    ) -> None:
        decision = await self._get_link_snapshot_decision(content_object.id)
        if decision is None:
            self.session.add(
                ContentLinkSnapshotDecision(
                    content_object_id=content_object.id,
                    owner_user_id=content_object.owner_user_id,
                    status=status,
                )
            )
            return
        decision.status = status
        decision.updated_at = datetime.now(UTC)

    def _text_link_urls(self, content_object: ContentObject) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for asset in content_object.assets:
            if asset.media_type != "text":
                continue
            text_body = self._read_text_asset_user_body(asset) or asset.text_content or ""
            links, _ = self._extract_links_from_text(text_body)
            for url in links:
                if self._is_generated_favicon_url(url):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)
        return urls

    @staticmethod
    def _link_asset_urls(content_object: ContentObject) -> list[str]:
        urls: list[str] = []
        for asset in content_object.assets:
            if asset.media_type != "link" or not asset.text_content:
                continue
            urls.append(asset.text_content.strip())
        return urls

    def _remaining_text_link_urls(self, content_object: ContentObject) -> list[str]:
        existing = set(self._link_asset_urls(content_object))
        return [url for url in self._text_link_urls(content_object) if url not in existing]

    @staticmethod
    def _is_generated_favicon_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.hostname == "favicon.yandex.net"

    async def _source_metadata_for_object(
        self,
        content_object: ContentObject,
    ) -> tuple[SourceMetadataResponse | None, dict[str, SourceMetadataResponse]]:
        asset_ids = [asset.id for asset in content_object.assets]
        conditions = [ContentSource.content_object_id == content_object.id]
        if asset_ids:
            conditions.append(ContentSource.content_asset_id.in_(asset_ids))
        query = (
            select(ContentSource)
            .where(
                ContentSource.owner_user_id == content_object.owner_user_id,
                or_(*conditions),
            )
            .order_by(ContentSource.created_at.asc())
        )
        records = list(await self.session.scalars(query))
        object_source = None
        asset_sources: dict[str, SourceMetadataResponse] = {}
        source_responses: list[SourceMetadataResponse] = []
        for record in records:
            response = self._source_response(record)
            source_responses.append(response)
            if record.content_asset_id:
                asset_sources.setdefault(record.content_asset_id, response)
            elif record.content_object_id == content_object.id and object_source is None:
                object_source = response
        if object_source is not None:
            object_source = self._merge_source_metadata(object_source, source_responses)
        asset_sources = {
            asset_id: self._merge_source_metadata(source, source_responses)
            for asset_id, source in asset_sources.items()
        }
        return object_source, asset_sources

    @staticmethod
    def _source_response(record: ContentSource) -> SourceMetadataResponse:
        return SourceMetadataResponse(
            provider=record.provider,
            provider_label=record.provider_label,
            external_id=record.external_id,
            url=record.source_url,
            title=record.title,
            original_created_at=record.original_created_at,
            origin=record.origin,
            author=record.author,
            group_id=record.group_id,
            entities=record.entities or [],
            custom_emoji_ids=record.custom_emoji_ids or [],
            raw_payload=record.raw_payload,
            metadata=record.source_metadata or {},
        )

    @staticmethod
    def _merge_source_metadata(
        base: SourceMetadataResponse,
        sources: list[SourceMetadataResponse],
    ) -> SourceMetadataResponse:
        custom_emoji_ids = list(dict.fromkeys(base.custom_emoji_ids))
        custom_emoji_assets: dict[str, Any] = {}
        for source in sources:
            for custom_emoji_id in source.custom_emoji_ids:
                if custom_emoji_id not in custom_emoji_ids:
                    custom_emoji_ids.append(custom_emoji_id)
            assets = source.metadata.get("custom_emoji_assets")
            if not isinstance(assets, dict):
                continue
            for custom_emoji_id, asset in assets.items():
                if isinstance(custom_emoji_id, str):
                    custom_emoji_assets.setdefault(custom_emoji_id, asset)

        metadata = dict(base.metadata)
        if custom_emoji_assets:
            existing_assets = metadata.get("custom_emoji_assets")
            merged_assets = dict(existing_assets) if isinstance(existing_assets, dict) else {}
            for custom_emoji_id, asset in custom_emoji_assets.items():
                merged_assets.setdefault(custom_emoji_id, asset)
            metadata["custom_emoji_assets"] = merged_assets

        return base.model_copy(
            update={
                "custom_emoji_ids": custom_emoji_ids,
                "metadata": metadata,
            }
        )

    @staticmethod
    def _snapshot_views_for_asset(
        *,
        asset: ContentAsset,
        asset_url: str,
        markdown: SnapshotArtifactReference | None,
        pdf: SnapshotArtifactReference | None,
        html: SnapshotArtifactReference | None,
    ) -> list[SnapshotViewResponse]:
        if asset.media_type == "text":
            return []

        views: list[SnapshotViewResponse] = []
        if markdown is not None or ContentService._is_markdown_asset(asset):
            views.append(
                SnapshotViewResponse(
                    kind="markdown",
                    label="MD",
                    url=markdown.url if markdown is not None else asset_url,
                )
            )
        if pdf is not None or ContentService._is_pdf_asset(asset):
            views.append(
                SnapshotViewResponse(
                    kind="pdf",
                    label="PDF",
                    url=pdf.url if pdf is not None else asset_url,
                )
            )
        if html is not None:
            views.append(
                SnapshotViewResponse(
                    kind="webpage_html",
                    label="Website",
                    url=html.url,
                )
            )
        return list(reversed(views))

    def _manifest(
        self,
        content_object: ContentObject,
        *,
        items: list[ContentObject],
        assignment: TaxonomyContentAssignment | None,
        tags: list[Tag],
    ) -> dict[str, object]:
        return {
            "id": content_object.id,
            "slug": content_object.slug,
            "kind": content_object.kind,
            "media_type": content_object.media_type,
            "title": content_object.title,
            "source_filename": content_object.source_filename,
            "folder": (assignment.category_path_snapshot if assignment is not None else None),
            "tags": [tag.slug for tag in tags],
            "items": [item.slug for item in items],
        }

    @staticmethod
    def _external_search_match_score(
        content_object_id: str,
        search_matches_by_object_id: dict[str, list[SearchContentMatch]] | None,
    ) -> float:
        if search_matches_by_object_id is None:
            return 0.0
        return max(
            (match.score for match in search_matches_by_object_id.get(content_object_id, [])),
            default=0.0,
        )

    @classmethod
    def _local_search_score(
        cls,
        content_object: ContentObject,
        search: str | None,
        *,
        active_tags: list[Tag],
        assignment: TaxonomyContentAssignment | None,
    ) -> float:
        if not search:
            return 0.0
        term_groups = cls._search_term_groups(search)
        if not term_groups:
            return 0.0
        parts = cls._local_search_parts(
            content_object,
            active_tags=active_tags,
            assignment=assignment,
        )
        if not parts:
            return 0.0

        normalized_query = search.casefold().strip()
        has_specific_query_term = any(not is_generic for _, is_generic in term_groups)
        matched_specific = False
        matched_groups = 0
        score = 0.0

        for variants, is_generic in term_groups:
            group_score = 0.0
            for text, weight in parts:
                lowered = text.casefold()
                if normalized_query and normalized_query in lowered:
                    group_score = max(group_score, weight * 3)
                for variant in variants:
                    if variant and variant in lowered:
                        group_score = max(group_score, weight)
            if group_score <= 0:
                continue
            matched_groups += 1
            score += group_score
            if not is_generic:
                matched_specific = True

        if matched_groups == 0:
            return 0.0
        if has_specific_query_term and not matched_specific:
            return 0.0
        if matched_groups == len(term_groups):
            score *= 2
        return score

    @staticmethod
    def _local_search_parts(
        content_object: ContentObject,
        *,
        active_tags: list[Tag],
        assignment: TaxonomyContentAssignment | None,
    ) -> list[tuple[str, float]]:
        parts: list[tuple[str, float]] = []
        if content_object.title:
            parts.append((content_object.title, 8.0))
        if content_object.source_filename:
            parts.append((content_object.source_filename, 4.0))
        if assignment is not None:
            parts.append((assignment.category_path_snapshot, 5.0))
            parts.append((assignment.category_name_snapshot, 5.0))
        for tag in active_tags:
            parts.append((tag.name, 10.0))
            parts.append((tag.slug, 8.0))
        for tag in content_object.tags:
            parts.append((tag.name, 10.0))
            parts.append((tag.slug, 8.0))
        for asset in content_object.assets:
            if asset.filename:
                parts.append((asset.filename, 4.0))
            if asset.text_content:
                parts.append((asset.text_content, 3.0))
        return parts

    @classmethod
    def _search_term_groups(cls, search: str) -> list[tuple[tuple[str, ...], bool]]:
        groups: list[tuple[tuple[str, ...], bool]] = []
        seen: set[str] = set()
        for raw_term in re.findall(r"[0-9A-Za-zА-Яа-яЁё_]{2,}", search.casefold()):
            term = raw_term.strip("_")
            if not term or term in seen:
                continue
            seen.add(term)
            variants, is_generic = cls._search_variants(term)
            groups.append((tuple(sorted(variants, key=len, reverse=True)), is_generic))
        return groups

    @staticmethod
    def _search_variants(term: str) -> tuple[set[str], bool]:
        variants = {term}
        is_generic = term in {"new", "latest", "fresh"} or term.startswith("нов")
        if re.search(r"[а-яё]", term) and len(term) >= 4:
            variants.add(term[:-1])

        if term in {"new", "latest", "fresh"}:
            variants.update(
                {
                    "new",
                    "latest",
                    "fresh",
                    "нов",
                    "анонс",
                    "announc",
                    "релиз",
                    "release",
                    "update",
                    "обнов",
                    "апдейт",
                    "выйдет",
                }
            )
            is_generic = True
        if term.startswith("нов"):
            variants.update(
                {
                    "нов",
                    "new",
                    "анонс",
                    "announc",
                    "релиз",
                    "release",
                    "update",
                    "обнов",
                    "апдейт",
                    "выйдет",
                }
            )
            is_generic = True
        if term in {"game", "games", "gaming"}:
            variants.update({"game", "games", "gaming", "video game", "игр"})
            is_generic = False
        if term.startswith("игр") or term in {"игра", "игры", "игру", "игре"}:
            variants.update({"игр", "game", "games", "gaming", "video game"})
            is_generic = False
        return {variant for variant in variants if len(variant) >= 2}, is_generic

    @staticmethod
    def _telegram_chat_type(origin: dict[str, Any] | None) -> str | None:
        if not isinstance(origin, dict):
            return None
        origin_type = origin.get("type")
        if origin_type == "user":
            return "private"
        if origin_type == "chat":
            return "group"
        if origin_type == "channel":
            return "channel"
        return str(origin_type) if origin_type else None

    async def _classification_text_excerpt(
        self,
        content_object: ContentObject,
        *,
        max_chars: int,
    ) -> str | None:
        parts: list[str] = []
        for asset in content_object.assets:
            if asset.text_content is not None and asset.text_content.strip():
                parts.append(asset.text_content.strip())
                continue
            if asset.media_type != "text":
                snapshot_text = await self.snapshots.get_markdown_text(
                    source_asset_id=asset.id,
                    max_chars=max_chars,
                )
                if snapshot_text:
                    parts.append(snapshot_text.strip())
        text = "\n\n".join(parts).strip()
        if not text:
            return None
        return text[:max_chars]

    async def _folder_counts(self, *, owner_user_id: str) -> dict[str, tuple[int, int]]:
        categories = await self.taxonomy.repository.list_categories(
            owner_user_id=owner_user_id,
            include_archived=False,
        )
        paths = [category.path for category in categories]
        direct_counts = {path: 0 for path in paths}
        total_counts = {path: 0 for path in paths}
        assignments = await self._current_assignment_map(owner_user_id)
        for content_object in await self.content.list_all(owner_user_id=owner_user_id):
            if not self._is_visible_note(content_object):
                continue
            assignment = assignments.get(content_object.id)
            if assignment is None:
                continue
            assigned_path = assignment.category_path_snapshot
            if assigned_path in direct_counts:
                direct_counts[assigned_path] += 1
            for path in paths:
                if self._path_matches_or_descends(assigned_path, path):
                    total_counts[path] += 1
        return {path: (direct_counts[path], total_counts[path]) for path in paths}

    @staticmethod
    def _is_visible_note(content_object: ContentObject) -> bool:
        return not (content_object.kind != "collection" and content_object.collection_memberships)

    @staticmethod
    def _path_matches_or_descends(candidate_path: str, parent_path: str) -> bool:
        return candidate_path == parent_path or candidate_path.startswith(f"{parent_path}/")

    @staticmethod
    def _folder_response(
        category: TaxonomyCategory,
        *,
        direct_count: int = 0,
        total_count: int = 0,
    ) -> FolderResponse:
        return FolderResponse(
            id=category.id,
            name=category.name,
            slug=category.slug,
            path=category.path,
            direct_count=direct_count,
            total_count=total_count,
        )

    @staticmethod
    def _folder_tree_item(
        category: TaxonomyCategory,
        *,
        direct_count: int = 0,
        total_count: int = 0,
    ) -> FolderTreeItem:
        return FolderTreeItem(
            id=category.id,
            name=category.name,
            slug=category.slug,
            path=category.path,
            direct_count=direct_count,
            total_count=total_count,
            children=[],
        )

    @staticmethod
    def _taxonomy_category_response_from_assignment(
        assignment: TaxonomyContentAssignment | None,
    ) -> ContentTaxonomyCategoryResponse | None:
        if assignment is None:
            return None
        return ContentTaxonomyCategoryResponse(
            id=assignment.category_id,
            name=assignment.category_name_snapshot,
            slug=assignment.category_path_snapshot.rsplit("/", 1)[-1],
            path=assignment.category_path_snapshot,
        )

    async def _current_assignment_map(
        self,
        owner_user_id: str,
    ) -> dict[str, TaxonomyContentAssignment]:
        assignments = await self.taxonomy.repository.list_current_assignments(
            owner_user_id=owner_user_id,
        )
        return {assignment.content_object_id: assignment for assignment in assignments}

    @staticmethod
    def _tag_response(tag: Tag, *, count: int = 0) -> TagResponse:
        return TagResponse(id=tag.id, name=tag.name, slug=tag.slug, count=count)

    @staticmethod
    def _media_type(filename: str, content_type: str | None) -> str:
        if content_type:
            if content_type.startswith("image/"):
                return "image"
            if content_type.startswith("audio/"):
                return "audio"
            if content_type.startswith("video/"):
                return "video"
            if content_type.startswith("text/"):
                return "text"
        suffix = Path(filename).suffix.lower()
        if suffix in {".txt", ".md", ".markdown"}:
            return "text"
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            return "image"
        if suffix in {".mp3", ".wav", ".ogg"}:
            return "audio"
        if suffix in {".mp4", ".mov", ".webm"}:
            return "video"
        return "document"

    @staticmethod
    def _is_markdown_asset(asset: ContentAsset) -> bool:
        suffix = Path(asset.filename).suffix.lower()
        return asset.mime_type == "text/markdown" or suffix in {".md", ".markdown"}

    @staticmethod
    def _is_pdf_asset(asset: ContentAsset) -> bool:
        return asset.mime_type == "application/pdf" or Path(asset.filename).suffix.lower() == ".pdf"

    @staticmethod
    def _extract_links_from_text(text: str) -> tuple[list[str], str]:
        """Extract HTTP/HTTPS URLs and preserve text with markdown link previews."""
        link_re = re.compile(r"(?<!!)\[([^\]\n]+)\]\((https?://[^\s)]+)\)|(https?://\S+)")
        links: list[str] = []
        seen: set[str] = set()
        formatted_parts: list[str] = []
        last_end = 0
        for match in link_re.finditer(text):
            label = match.group(1)
            markdown_url = match.group(2)
            bare_url = match.group(3)
            raw = markdown_url or bare_url or ""
            url = raw.rstrip(".,;:!?)]\\'\">`") if bare_url else raw.rstrip(".,;:!?\\'\">`")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                formatted_parts.append(text[last_end : match.end()])
                last_end = match.end()
                continue
            formatted_parts.append(text[last_end : match.start()])
            formatted_parts.append(ContentService._markdown_link_with_favicon(url, label=label))
            if url not in seen:
                seen.add(url)
                links.append(url)
            last_end = match.end() if markdown_url else match.start() + len(url)
        formatted_parts.append(text[last_end:])
        return links, "".join(formatted_parts)

    @staticmethod
    def _markdown_link_with_favicon(url: str, *, label: str | None = None) -> str:
        parsed = urlparse(url)
        favicon_url = f"https://favicon.yandex.net/favicon/{parsed.hostname or url}"
        link_label = label.strip() if label and label.strip() else url
        return f"![favicon]({favicon_url}) [{link_label}]({url})"

    @staticmethod
    def _plain_url(value: str) -> str | None:
        candidate = value.strip()
        if not candidate or any(character.isspace() for character in candidate):
            return None
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return None
        return candidate

    @staticmethod
    def _link_only_url(value: str) -> str | None:
        plain = ContentService._plain_url(value)
        if plain is not None:
            return plain

        candidate = value.strip()
        match = re.fullmatch(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", candidate)
        if match is None:
            return None

        label = match.group(1).strip()
        url = match.group(2).rstrip(".,;:!?\\'\">`")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return None
        return url if label == url else None

    async def _resolve_link_title(self, *, url: str, title: str | None) -> str:
        if title and not self._title_is_url_placeholder(title, url):
            explicit_title = _normalize_title(title)
            if explicit_title:
                return explicit_title

        fetched_title = await self._fetch_link_page_title(url)
        return _normalize_title(fetched_title, self._link_title(url))

    @staticmethod
    def _title_is_url_placeholder(title: str, url: str) -> bool:
        cleaned = _strip_title_markdown(title)
        if not cleaned.startswith(("http://", "https://")):
            return False
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return False
        return cleaned == url or url.startswith(cleaned) or cleaned.startswith(url)

    @staticmethod
    async def _fetch_link_page_title(url: str) -> str | None:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=LINK_TITLE_FETCH_TIMEOUT_SECONDS,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "Seyvix link title fetcher",
                },
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.info("content.note.link_title_fetch_failed", url=url, error=str(exc))
            return None

        if response.status_code >= 400:
            logger.info(
                "content.note.link_title_fetch_bad_status",
                url=url,
                status_code=response.status_code,
            )
            return None

        content_type = response.headers.get("content-type", "")
        if content_type and "html" not in content_type.lower():
            return None

        return ContentService._title_from_html(response.text[:LINK_TITLE_FETCH_MAX_CHARS])

    @staticmethod
    def _title_from_html(html: str) -> str | None:
        match = re.search(r"<title\b[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if match is None:
            return None
        title = re.sub(r"\s+", " ", unescape(match.group(1))).strip()
        return title or None

    @staticmethod
    def _link_title(url: str) -> str:
        parsed = urlparse(url)
        return parsed.hostname or url

    @staticmethod
    def _decode_text(data: bytes) -> str | None:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    @staticmethod
    def _user_text_from_stored_markdown(file_text: str) -> str | None:
        """Invert `ContentStorage.write_text_object`."""
        if not file_text.startswith("# "):
            return None
        sep = file_text.find("\n\n", 2)
        if sep == -1:
            return None
        body = file_text[sep + 2 :]
        if body.endswith("\n"):
            body = body[:-1]
        return body

    def _read_text_asset_user_body(self, asset: ContentAsset) -> str | None:
        if asset.media_type != "text" or not asset.storage_path:
            return None
        try:
            data = self.storage.read_relative_file(asset.storage_path)
        except Exception:  # noqa: BLE001
            return None
        decoded = self._decode_text(data)
        if decoded is None:
            return None
        return self._user_text_from_stored_markdown(decoded)
