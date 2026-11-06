"""Public API of the content module.

`ContentService` is a thin facade over focused components (writer, deleter, lister, card
builder, export) used by the REST router and by other modules (Telegram ingest, vectorization).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.content.cards import CardBuilder, tag_response
from app.modules.content.contracts import ContentClassificationInput
from app.modules.content.deletion import NoteDeleter
from app.modules.content.errors import (
    FolderNotFoundError,
    NoteNotFoundError,
    ThumbnailPendingError,
    ThumbnailUnavailableError,
)
from app.modules.content.export import build_manifest, stream_note_archive
from app.modules.content.infrastructure.repositories import ContentRepository
from app.modules.content.listing import NoteFilters, NoteLister
from app.modules.content.models import ContentObject
from app.modules.content.schemas import (
    FileUploadResponse,
    FolderDetailResponse,
    FolderResponse,
    FolderTreeItem,
    FolderTreeResponse,
    NoteCardResponse,
    NoteListResponse,
)
from app.modules.content.sync import ChangeSet, load_changes
from app.modules.content.text import as_uuid
from app.modules.content.text_input import load_content_text_input
from app.modules.content.uploads import PendingUploads, UploadedContent
from app.modules.content.writer import NoteWriter
from app.modules.search.schemas import SearchContentMatch
from app.modules.snapshots.service import SnapshotFile, SnapshotService
from app.modules.tags.service import TagsService
from app.modules.taxonomy.models import TaxonomyContentAssignment
from app.modules.taxonomy.service import TaxonomyService
from app.platform.storage.service import StorageBackend

__all__ = [
    "AssetFile",
    "ContentService",
    "FolderNotFoundError",
    "NoteNotFoundError",
    "ThumbnailPendingError",
    "ThumbnailUnavailableError",
    "UploadedContent",
]


@dataclass(frozen=True, slots=True)
class AssetFile:
    storage_key: str
    filename: str
    mime_type: str
    size_bytes: int
    # Text assets are rewritten in place on edit, so they must be revalidated.
    mutable: bool


@dataclass(frozen=True, slots=True)
class NoteChanges:
    changes: ChangeSet
    cards: list[NoteCardResponse]


class ContentService:
    def __init__(self, session: AsyncSession, storage: StorageBackend) -> None:
        self.session = session
        self.storage = storage
        self.content = ContentRepository(session)
        self.tags = TagsService(session)
        self.taxonomy = TaxonomyService(session)
        self.snapshots = SnapshotService(session, storage)
        self.lister = NoteLister(session)
        self.cards = CardBuilder(
            session,
            snapshots=self.snapshots,
            tags=self.tags,
            api_prefix=get_settings().api_prefix,
        )
        self.writer = NoteWriter(
            session, storage, repository=self.content, tags=self.tags, taxonomy=self.taxonomy
        )
        self.deleter = NoteDeleter(
            session, storage, repository=self.content, taxonomy=self.taxonomy
        )

    # --- creation ---------------------------------------------------------------------

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
        object_id = await self.writer.create_note(
            owner_user_id=owner_user_id,
            media_type=media_type,
            text=text,
            title=title,
            folder_path=folder_path,
            tag_names=tag_names,
            file_upload_ids=file_upload_ids,
        )
        return await self._fresh_card(owner_user_id, object_id)

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
        if not create_or_attach_object:
            return await PendingUploads(self.session, self.storage).create(
                owner_user_id=owner_user_id, files=files
            )
        created_id = await self.writer.upload_files(
            owner_user_id=owner_user_id,
            files=files,
            title=title,
            folder_path=folder_path,
            tag_names=tag_names,
            object_id=object_id,
        )
        return await self._fresh_card(owner_user_id, created_id)

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
        object_id = await self.writer.create_composite_from_files(
            owner_user_id=owner_user_id,
            files=files,
            text=text,
            title=title,
            folder_path=folder_path,
            tag_names=tag_names,
        )
        return await self._fresh_card(owner_user_id, object_id)

    async def attach_source_metadata(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        source: dict[str, Any],
        content_asset_id: str | None = None,
    ) -> None:
        """Stages the source row (flushes, does not commit)."""
        await self.writer.attach_source_metadata(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            source=source,
            content_asset_id=content_asset_id,
        )

    # --- reading ----------------------------------------------------------------------

    async def get_note(self, *, owner_user_id: str, slug: str) -> NoteCardResponse:
        content_object = await self._load_note(owner_user_id=owner_user_id, ref=slug)
        return (await self._full_cards(owner_user_id, [content_object.id]))[0]

    async def list_notes(
        self,
        *,
        owner_user_id: str,
        tag_slugs: list[str],
        folder_path: str | None,
        sort: str,
        search_result_ids: list[str] | None = None,
        search_matches_by_object_id: dict[str, list[SearchContentMatch]] | None = None,
        content_types: list[str] | None = None,
        source_providers: list[str] | None = None,
        is_favorite: bool | None = None,
        created_at_from: datetime | None = None,
        created_at_to: datetime | None = None,
        card_view: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> NoteListResponse:
        page = await self.lister.list_ids(
            owner_user_id=owner_user_id,
            filters=NoteFilters(
                tag_slugs=tag_slugs,
                folder_path=folder_path,
                content_types=content_types or [],
                source_providers=source_providers or [],
                is_favorite=is_favorite,
                created_at_from=created_at_from,
                created_at_to=created_at_to,
            ),
            sort=sort,
            limit=limit,
            offset=offset,
            search_ids=search_result_ids,
        )
        if card_view:
            items = await self.summary_cards(
                owner_user_id, page.ids, search_matches=search_matches_by_object_id
            )
        else:
            items = await self._full_cards(
                owner_user_id, page.ids, search_matches=search_matches_by_object_id
            )
        return NoteListResponse(items=items, next_offset=page.next_offset)

    async def summary_cards(
        self,
        owner_user_id: str,
        ids: Sequence[str],
        *,
        search_matches: dict[str, list[SearchContentMatch]] | None = None,
    ) -> list[NoteCardResponse]:
        objects = await self._ordered(owner_user_id, ids)
        return await self.cards.summary_cards(objects, search_matches=search_matches)

    async def list_changes(self, *, owner_user_id: str, since: str | None) -> NoteChanges:
        changes = await load_changes(self.session, owner_user_id=owner_user_id, since=since)
        cards = await self.summary_cards(owner_user_id, changes.changed_ids)
        return NoteChanges(changes=changes, cards=cards)

    async def list_trash(self, *, owner_user_id: str) -> NoteListResponse:
        ids = await self.lister.trash_ids(owner_user_id=owner_user_id)
        return NoteListResponse(items=await self._full_cards(owner_user_id, ids))

    async def get_asset_file(self, *, owner_user_id: str, slug: str, asset_id: str) -> AssetFile:
        content_object = await self._load_note(owner_user_id=owner_user_id, ref=slug)
        asset = next((a for a in content_object.assets if a.id == asset_id), None)
        if asset is None:
            raise NoteNotFoundError
        return AssetFile(
            storage_key=asset.storage_key,
            filename=asset.filename,
            mime_type=asset.mime_type or "application/octet-stream",
            size_bytes=asset.size_bytes,
            mutable=asset.media_type == "text",
        )

    async def get_asset_thumbnail(
        self, *, owner_user_id: str, slug: str, asset_id: str
    ) -> SnapshotFile:
        content_object = await self._load_note(owner_user_id=owner_user_id, ref=slug)
        if not any(asset.id == asset_id for asset in content_object.assets):
            raise NoteNotFoundError
        thumbnail = await self.snapshots.get_thumbnail(source_asset_id=asset_id)
        if thumbnail is None or thumbnail.key is None:
            if await self.snapshots.is_thumbnail_unavailable(source_asset_id=asset_id):
                raise ThumbnailUnavailableError
            raise ThumbnailPendingError
        return thumbnail

    async def note_archive(
        self, *, owner_user_id: str, slug: str
    ) -> tuple[str, AsyncIterator[bytes]]:
        """Archive file name and a streaming zip body (the tree is loaded up front)."""
        content_object = await self._load_note(owner_user_id=owner_user_id, ref=slug)
        tree = await self._ordered(owner_user_id, [content_object.id], include_deleted=True)
        root = tree[0]
        tree_ids = await self.content.descendant_ids([root.id])
        tags = await self.tags.list_active_tags_for_contents(
            owner_user_id=owner_user_id, content_object_ids=tree_ids
        )
        folders = await self._folders(owner_user_id, tree_ids)
        manifest = build_manifest(
            root,
            folders=folders,
            tags={object_id: [tag.slug for tag in items] for object_id, items in tags.items()},
        )
        await self.session.commit()  # release the connection before streaming starts
        return f"{root.slug}.zip", stream_note_archive(self.storage, root, manifest)

    async def build_classification_input(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        text_excerpt_max_chars: int = 4000,
    ) -> ContentClassificationInput:
        text_input = await load_content_text_input(
            self.session,
            self.storage,
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            max_chars=text_excerpt_max_chars,
        )
        if text_input is None:
            raise NoteNotFoundError
        tags = (
            await self.tags.list_active_tags_for_contents(
                owner_user_id=owner_user_id, content_object_ids=[content_object_id]
            )
        ).get(content_object_id, [])
        return ContentClassificationInput(
            content_object_id=text_input.content_object_id,
            title=text_input.title,
            text_excerpt=text_input.text_excerpt,
            url=text_input.url,
            tags=[tag.slug for tag in sorted(tags, key=lambda tag: tag.name)],
            metadata=text_input.metadata,
            created_at=text_input.created_at,
            updated_at=text_input.updated_at,
        )

    # --- edits ------------------------------------------------------------------------

    async def update_note(
        self,
        *,
        owner_user_id: str,
        slug: str,
        title: str | None,
        text: str | None,
        tag_names: list[str] | None,
    ) -> NoteCardResponse:
        content_object = await self._load_note(owner_user_id=owner_user_id, ref=slug)
        await self.writer.update_note(content_object, title=title, text=text, tag_names=tag_names)
        return await self._fresh_card(owner_user_id, content_object.id)

    async def set_favorite(
        self, *, owner_user_id: str, slug: str, is_favorite: bool
    ) -> NoteCardResponse:
        content_object = await self._load_note(owner_user_id=owner_user_id, ref=slug)
        await self.writer.set_favorite(content_object, is_favorite=is_favorite)
        return await self._fresh_card(owner_user_id, content_object.id)

    async def reorder(self, *, owner_user_id: str, positions: dict[str, int]) -> None:
        await self.writer.reorder(owner_user_id=owner_user_id, positions=positions)

    async def merge_notes(
        self,
        *,
        owner_user_id: str,
        target_slug: str,
        source_slugs: list[str],
        title: str | None,
    ) -> NoteCardResponse:
        target = await self._load_note(owner_user_id=owner_user_id, ref=target_slug)
        collection_id = await self.writer.merge_notes(
            owner_user_id=owner_user_id, target=target, source_slugs=source_slugs, title=title
        )
        return await self._fresh_card(owner_user_id, collection_id)

    async def remove_collection_items(
        self, *, owner_user_id: str, collection_slug: str, item_slugs: list[str]
    ) -> None:
        collection = await self._load_note(owner_user_id=owner_user_id, ref=collection_slug)
        await self.writer.remove_collection_items(collection, item_slugs=item_slugs)

    async def decide_deferred_link_snapshots(
        self, *, owner_user_id: str, slug: str, decision: str
    ) -> NoteCardResponse:
        content_object = await self._load_note(owner_user_id=owner_user_id, ref=slug)
        await self.writer.decide_deferred_link_snapshots(content_object, decision=decision)
        return await self._fresh_card(owner_user_id, content_object.id)

    # --- trash ------------------------------------------------------------------------

    async def delete_notes(self, *, owner_user_id: str, slugs: list[str]) -> None:
        await self.deleter.delete_notes(owner_user_id=owner_user_id, slugs=slugs)

    async def restore_note(self, *, owner_user_id: str, slug: str) -> NoteCardResponse:
        object_id = await self.deleter.restore(owner_user_id=owner_user_id, slug=slug)
        return await self._fresh_card(owner_user_id, object_id)

    async def cleanup_expired_trash(self, *, owner_user_id: str) -> int:
        return await self.deleter.cleanup_expired_trash(owner_user_id=owner_user_id)

    # --- folders ----------------------------------------------------------------------

    async def list_folders(self, *, owner_user_id: str) -> FolderTreeResponse:
        categories = await self.lister.categories(owner_user_id=owner_user_id)
        stats = await self.lister.folder_stats(
            owner_user_id=owner_user_id, paths=[category.path for category in categories]
        )
        by_id = {
            category.id: FolderTreeItem(
                id=category.id,
                name=category.name,
                slug=category.slug,
                path=category.path,
                direct_count=stats.direct.get(category.path, 0),
                total_count=stats.total.get(category.path, 0),
                children=[],
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
        self, *, owner_user_id: str, folder_path: str
    ) -> FolderDetailResponse:
        category = await self.taxonomy.repository.get_category_by_path(
            owner_user_id=owner_user_id, path=folder_path, include_archived=False
        )
        if category is None:
            raise FolderNotFoundError
        stats = await self.lister.folder_stats(owner_user_id=owner_user_id, paths=[category.path])
        page = await self.lister.list_ids(
            owner_user_id=owner_user_id,
            filters=NoteFilters(folder_path=folder_path),
            sort="newest",
            limit=None,
            offset=0,
        )
        tag_counts = await self.lister.folder_tag_counts(
            owner_user_id=owner_user_id, folder_path=folder_path
        )
        return FolderDetailResponse(
            folder=FolderResponse(
                id=category.id,
                name=category.name,
                slug=category.slug,
                path=category.path,
                direct_count=stats.direct.get(category.path, 0),
                total_count=stats.total.get(category.path, 0),
            ),
            tags=[tag_response(tag, count=count) for tag, count in tag_counts],
            notes=await self._full_cards(owner_user_id, page.ids),
        )

    # --- helpers ----------------------------------------------------------------------

    async def _load_note(self, *, owner_user_id: str, ref: str) -> ContentObject:
        value = ref.strip()
        object_id = as_uuid(value)
        content_object: ContentObject | None = None
        if object_id is not None:
            content_object = await self.content.get_by_id(
                owner_user_id=owner_user_id, object_id=object_id
            ) or await self.content.get_by_asset_id(owner_user_id=owner_user_id, asset_id=object_id)
        if content_object is None:
            content_object = await self.content.get_by_slug(owner_user_id=owner_user_id, slug=value)
        if content_object is None:
            raise NoteNotFoundError
        return content_object

    async def _ordered(
        self, owner_user_id: str, ids: Sequence[str], *, include_deleted: bool = False
    ) -> list[ContentObject]:
        """Objects in `ids` order with their whole collection tree loaded."""
        if not ids:
            return []
        tree_ids = await self.content.descendant_ids(list(ids))
        objects = await self.content.list_by_ids(
            owner_user_id=owner_user_id, ids=tree_ids, include_deleted=True
        )
        by_id = {obj.id: obj for obj in objects}
        return [
            by_id[object_id]
            for object_id in ids
            if object_id in by_id and (include_deleted or by_id[object_id].deleted_at is None)
        ]

    async def _full_cards(
        self,
        owner_user_id: str,
        ids: Sequence[str],
        *,
        search_matches: dict[str, list[SearchContentMatch]] | None = None,
    ) -> list[NoteCardResponse]:
        objects = await self._ordered(owner_user_id, ids, include_deleted=True)
        return await self.cards.full_cards(objects, search_matches=search_matches)

    async def _fresh_card(self, owner_user_id: str, object_id: str) -> NoteCardResponse:
        self.session.expunge_all()  # drop pre-commit state; reload the committed tree
        cards = await self._full_cards(owner_user_id, [object_id])
        if not cards:
            raise NoteNotFoundError
        return cards[0]

    async def _folders(self, owner_user_id: str, ids: Sequence[str]) -> dict[str, str]:
        rows = await self.session.execute(
            select(
                TaxonomyContentAssignment.content_object_id,
                TaxonomyContentAssignment.category_path_snapshot,
            ).where(
                TaxonomyContentAssignment.owner_user_id == owner_user_id,
                TaxonomyContentAssignment.content_object_id.in_(list(ids)),
                TaxonomyContentAssignment.is_current.is_(True),
            )
        )
        return {object_id: path for object_id, path in rows.all()}
