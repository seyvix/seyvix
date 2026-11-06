"""Note mutations: creation from text/links/files, edits, merge/collections, link decisions.

Every public method runs one transaction: storage writes first (undone on failure), then the
DB rows, the outbox events and the change-feed bump, then a single commit. Slow network work
(link titles) happens before any query so no connection is held across it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import ContentObjectChangedPayload, EventEnvelope
from app.core.logging import get_logger
from app.modules.content.cards import (
    AUTO_LINK_SNAPSHOT_LIMIT,
    link_asset_urls,
    remaining_text_link_urls,
)
from app.modules.content.errors import NoteNotFoundError
from app.modules.content.infrastructure.repositories import ContentRepository
from app.modules.content.links import fetch_page_title
from app.modules.content.models import (
    ContentAsset,
    ContentCollectionItem,
    ContentFileUpload,
    ContentLinkSnapshotDecision,
    ContentObject,
    ContentSource,
)
from app.modules.content.sync import record_tombstones, touch_content_objects
from app.modules.content.text import (
    as_uuid,
    extract_links,
    link_host_title,
    link_only_url,
    normalize_title,
    optional_datetime,
    optional_dict,
    optional_list,
    optional_string,
    slugify,
    title_is_url_placeholder,
)
from app.modules.content.uploads import (
    FileFacts,
    PendingUploads,
    StorageWrites,
    UploadedContent,
    inspect_file,
    storage_transaction,
)
from app.modules.snapshots.service import reassign_asset_snapshots
from app.modules.tags.service import TagsService
from app.modules.taxonomy.models import TaxonomyContentAssignment
from app.modules.taxonomy.service import TaxonomyService
from app.platform.events import EventPublisher
from app.platform.storage.keys import asset_key
from app.platform.storage.service import StorageBackend

logger = get_logger(__name__)

DEFAULT_TEXT_TITLE = "Новая заметка"
FOLDER_REASONING = "Assigned from note folder path."


@dataclass(frozen=True, slots=True)
class _FileSource:
    """A file to attach: either a spooled local file or a pending upload in storage."""

    filename: str
    content_type: str | None
    size_bytes: int
    facts: FileFacts
    path: Path | None = None
    upload: ContentFileUpload | None = None


def _source_from_upload(upload: ContentFileUpload) -> _FileSource:
    return _FileSource(
        filename=upload.source_filename,
        content_type=upload.mime_type,
        size_bytes=upload.size_bytes,
        facts=FileFacts(
            media_type=upload.media_type,
            image_width=upload.image_width,
            image_height=upload.image_height,
            text_content=upload.text_content,
        ),
        upload=upload,
    )


class NoteWriter:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        *,
        repository: ContentRepository,
        tags: TagsService,
        taxonomy: TaxonomyService,
    ) -> None:
        self.session = session
        self.storage = storage
        self.repository = repository
        self.tags = tags
        self.taxonomy = taxonomy
        self.uploads = PendingUploads(session, storage)
        self.events = EventPublisher(session)

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
    ) -> str:
        """Returns the id of the created note."""
        if file_upload_ids:
            uploads = await self.uploads.take(
                owner_user_id=owner_user_id, upload_ids=file_upload_ids
            )
            if not uploads:
                raise NoteNotFoundError
            sources = [_source_from_upload(upload) for upload in uploads]
            if text is not None and len(sources) == 1:
                return await self._create_composite(
                    owner_user_id=owner_user_id,
                    sources=sources,
                    text=text,
                    title=title,
                    folder_path=folder_path,
                    tag_names=tag_names,
                    consumed=uploads,
                )
            return await self._create_from_files(
                owner_user_id=owner_user_id,
                sources=sources,
                title=title,
                folder_path=folder_path,
                tag_names=tag_names,
                object_id=None,
                consumed=uploads,
            )

        if media_type not in (None, "text", "link") or text is None:
            raise NoteNotFoundError
        links, text_with_links = extract_links(text)
        if links:
            single_url = link_only_url(text)
            if single_url is not None and len(links) == 1:
                return await self._create_link_note(
                    owner_user_id=owner_user_id,
                    url=single_url,
                    title=title,
                    folder_path=folder_path,
                    tag_names=tag_names,
                )
            return await self._create_text_with_links(
                owner_user_id=owner_user_id,
                text=text_with_links,
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

    async def upload_files(
        self,
        *,
        owner_user_id: str,
        files: Sequence[UploadedContent],
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
        object_id: str | None,
    ) -> str:
        sources = [await self._source_from_file(uploaded) for uploaded in files]
        return await self._create_from_files(
            owner_user_id=owner_user_id,
            sources=sources,
            title=title,
            folder_path=folder_path,
            tag_names=tag_names,
            object_id=object_id,
            consumed=[],
        )

    async def create_composite_from_files(
        self,
        *,
        owner_user_id: str,
        files: Sequence[UploadedContent],
        text: str | None,
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> str:
        if not files:
            if text is None:
                raise NoteNotFoundError
            return await self._create_text_note(
                owner_user_id=owner_user_id,
                text=text,
                title=title,
                folder_path=folder_path,
                tag_names=tag_names,
            )
        sources = [await self._source_from_file(uploaded) for uploaded in files]
        return await self._create_composite(
            owner_user_id=owner_user_id,
            sources=sources,
            text=text,
            title=title,
            folder_path=folder_path,
            tag_names=tag_names,
            consumed=[],
        )

    async def _source_from_file(self, uploaded: UploadedContent) -> _FileSource:
        return _FileSource(
            filename=uploaded.filename,
            content_type=uploaded.content_type,
            size_bytes=uploaded.size_bytes,
            facts=await inspect_file(uploaded),
            path=uploaded.path,
        )

    async def _create_text_note(
        self,
        *,
        owner_user_id: str,
        text: str,
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> str:
        normalized_title = normalize_title(title, text) or DEFAULT_TEXT_TITLE
        async with storage_transaction(self.session, self.storage) as writes:
            obj = await self._new_object(
                owner_user_id=owner_user_id,
                title=normalized_title,
                slug_source=normalized_title,
                kind="simple",
                media_type="text",
            )
            asset = await self._text_asset(writes, obj, text=text, role="original")
            obj.source_filename = asset.filename
            obj.mime_type = asset.mime_type
            obj.size_bytes = asset.size_bytes
            await self._finish_new(obj, [], folder_path=folder_path, tag_names=tag_names)
            await self.session.commit()
        return obj.id

    async def _create_link_note(
        self,
        *,
        owner_user_id: str,
        url: str,
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> str:
        normalized_title = ""
        if title and not title_is_url_placeholder(title, url):
            normalized_title = normalize_title(title)
        if not normalized_title:
            normalized_title = normalize_title(await fetch_page_title(url), link_host_title(url))
        async with storage_transaction(self.session, self.storage) as writes:
            obj = await self._new_object(
                owner_user_id=owner_user_id,
                title=normalized_title,
                slug_source=normalized_title,
                kind="complex",
                media_type="link",
                source_filename=url,
                mime_type="text/uri-list",
            )
            asset = await self._link_asset(writes, obj, url=url, filename="link.url")
            obj.size_bytes = asset.size_bytes
            await self._finish_new(obj, [], folder_path=folder_path, tag_names=tag_names)
            await self.session.commit()
        return obj.id

    async def _create_text_with_links(
        self,
        *,
        owner_user_id: str,
        text: str,
        title_source_text: str,
        links: list[str],
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> str:
        normalized_title = normalize_title(title, title_source_text, link_host_title(links[0]))
        async with storage_transaction(self.session, self.storage) as writes:
            obj = await self._new_object(
                owner_user_id=owner_user_id,
                title=normalized_title,
                slug_source=normalized_title,
                kind="complex",
                media_type="link",
                source_filename=links[0],
                mime_type="text/uri-list",
                size_bytes=len(links[0]) + 1,
            )
            for index, url in enumerate(links[:AUTO_LINK_SNAPSHOT_LIMIT], start=1):
                await self._link_asset(writes, obj, url=url, filename=f"link-{index}.url")
            if text.strip():
                await self._text_asset(writes, obj, text=text, role="text")
            await self._finish_new(obj, [], folder_path=folder_path, tag_names=tag_names)
            await self.session.commit()
        return obj.id

    async def _create_composite(
        self,
        *,
        owner_user_id: str,
        sources: Sequence[_FileSource],
        text: str | None,
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
        consumed: Sequence[ContentFileUpload],
    ) -> str:
        first = sources[0]
        normalized_title = normalize_title(title) if title is not None else normalize_title(text)
        if not normalized_title and title is None:
            normalized_title = PurePosixPath(first.filename).stem or "Telegram message"
        async with storage_transaction(self.session, self.storage) as writes:
            obj = await self._new_object(
                owner_user_id=owner_user_id,
                title=normalized_title,
                slug_source=normalized_title,
                kind="complex",
                media_type=first.facts.media_type,
                source_filename=first.filename,
                mime_type=first.content_type,
                size_bytes=first.size_bytes,
            )
            if text:
                await self._text_asset(writes, obj, text=text, role="text")
            for source in sources:
                await self._file_asset(writes, obj, source)
            await self._consume(consumed)
            await self._finish_new(obj, [], folder_path=folder_path, tag_names=tag_names)
            await self.session.commit()
        return obj.id

    async def _create_from_files(
        self,
        *,
        owner_user_id: str,
        sources: Sequence[_FileSource],
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
        object_id: str | None,
        consumed: Sequence[ContentFileUpload],
    ) -> str:
        if not sources:
            raise NoteNotFoundError
        if object_id is not None:
            object_id = as_uuid(object_id)
            if object_id is None:
                raise NoteNotFoundError
            # Serialize concurrent uploads that target the same object id (Telegram albums).
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"content-object:{object_id}"},
            )
        existing = (
            await self.repository.get_by_id(owner_user_id=owner_user_id, object_id=object_id)
            if object_id is not None
            else None
        )
        if object_id is not None and existing is None:
            taken = await self.session.scalar(
                select(ContentObject.id).where(ContentObject.id == object_id)
            )
            if taken is not None:
                raise NoteNotFoundError

        async with storage_transaction(self.session, self.storage) as writes:
            if existing is not None:
                collection = await self._ensure_collection(existing, title=title)
                assignment = await self._current_assignment(collection)
                child_folder = assignment.category_path_snapshot if assignment else folder_path
                position = await self.repository.next_collection_position(collection.id)
                children: list[ContentObject] = []
                for source in sources:
                    child = await self._file_object(writes, owner_user_id, source)
                    self._add_member(collection, child, position)
                    position += 10
                    children.append(child)
                await self._consume(consumed)
                await self.session.flush()
                for child in children:
                    await self._apply_tags_and_folder(child, child_folder, tag_names)
                    self._publish(child, "content.object.created")
                await touch_content_objects(self.session, [collection.id])
                self._publish(collection, "content.object.updated")
                await self.session.commit()
                return collection.id

            if len(sources) == 1:
                obj = await self._file_object(
                    writes, owner_user_id, sources[0], object_id=object_id, title=title
                )
                await self._consume(consumed)
                await self._finish_new(obj, [], folder_path=folder_path, tag_names=tag_names)
                await self.session.commit()
                return obj.id

            collection_title = normalize_title(title) or "Imported collection"
            collection = await self._new_object(
                owner_user_id=owner_user_id,
                title=collection_title,
                slug_source=collection_title,
                kind="collection",
                media_type=None,
                object_id=object_id,
            )
            children = []
            for position, source in enumerate(sources, start=1):
                child = await self._file_object(writes, owner_user_id, source)
                self._add_member(collection, child, position * 10)
                children.append(child)
            await self._consume(consumed)
            await self._finish_new(
                collection, children, folder_path=folder_path, tag_names=tag_names
            )
            await self.session.commit()
            return collection.id

    async def _file_object(
        self,
        writes: StorageWrites,
        owner_user_id: str,
        source: _FileSource,
        *,
        object_id: str | None = None,
        title: str | None = None,
    ) -> ContentObject:
        normalized_title = normalize_title(title) if title is not None else source.filename
        obj = await self._new_object(
            owner_user_id=owner_user_id,
            title=normalized_title[:512],
            slug_source=PurePosixPath(source.filename).stem or normalized_title or "uploaded-file",
            kind="complex" if source.facts.media_type == "document" else "simple",
            media_type=source.facts.media_type,
            source_filename=source.filename,
            mime_type=source.content_type,
            size_bytes=source.size_bytes,
            object_id=object_id,
        )
        await self._file_asset(writes, obj, source)
        return obj

    # --- edits ------------------------------------------------------------------------

    async def update_note(
        self,
        content_object: ContentObject,
        *,
        title: str | None,
        text: str | None,
        tag_names: list[str] | None,
    ) -> None:
        if title is not None:
            content_object.title = normalize_title(title) or content_object.title
        # The text file is overwritten in place (not undoable); `text_content` in the DB is
        # authoritative for rendering, the file only mirrors it for downloads/exports.
        if text is not None:
            text_asset = next(
                (asset for asset in content_object.assets if asset.media_type == "text"), None
            )
            if text_asset is not None:
                data = _text_file_bytes(content_object.title, text)
                stored = await self.storage.put_bytes(text_asset.storage_key, data, "text/markdown")
                text_asset.size_bytes = stored.size_bytes
                text_asset.checksum = stored.checksum
                text_asset.text_content = text
                if content_object.media_type == "text":
                    content_object.size_bytes = stored.size_bytes
                content_object.updated_at = datetime.now(UTC)
        if tag_names is not None:
            await self.tags.replace_manual_tags_for_content(
                owner_user_id=content_object.owner_user_id,
                content_object_id=content_object.id,
                tag_names=tag_names,
                assigned_by_user_id=content_object.owner_user_id,
            )
        await touch_content_objects(self.session, [content_object.id])
        self._publish(content_object, "content.object.updated")
        await self.session.commit()

    async def set_favorite(self, content_object: ContentObject, *, is_favorite: bool) -> None:
        content_object.is_favorite = is_favorite
        await touch_content_objects(self.session, [content_object.id])
        self._publish(content_object, "content.object.updated")
        await self.session.commit()

    async def reorder(self, *, owner_user_id: str, positions: dict[str, int]) -> None:
        if not positions:
            return
        found = await self.session.scalar(
            select(func.count()).where(
                ContentObject.owner_user_id == owner_user_id,
                ContentObject.slug.in_(list(positions)),
            )
        )
        if found != len(positions):
            raise NoteNotFoundError
        await self.session.execute(
            update(ContentObject)
            .where(
                ContentObject.owner_user_id == owner_user_id,
                ContentObject.slug.in_(list(positions)),
            )
            .values(
                sort_order=case(positions, value=ContentObject.slug),
                changed_at=func.clock_timestamp(),
                updated_at=ContentObject.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()

    async def attach_source_metadata(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        source: dict[str, Any],
        content_asset_id: str | None,
    ) -> None:
        provider = source.get("provider")
        external_id = source.get("external_id")
        if not isinstance(provider, str) or not provider or not isinstance(external_id, str):
            return
        record = await self.session.scalar(
            select(ContentSource).where(
                ContentSource.provider == provider,
                ContentSource.external_id == external_id,
                ContentSource.content_object_id == content_object_id,
            )
        )
        if record is None:
            record = ContentSource(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                provider=provider,
                provider_label=provider.title(),
                external_id=external_id,
            )
            self.session.add(record)
        record.content_asset_id = content_asset_id
        record.provider_label = str(source.get("provider_label") or provider.title())
        record.group_id = optional_string(source.get("group_id"))
        record.source_url = optional_string(source.get("url"))
        record.title = optional_string(source.get("title"))
        record.original_created_at = optional_datetime(source.get("original_created_at"))
        record.origin = optional_dict(source.get("origin"))
        record.author = optional_dict(source.get("author"))
        record.entities = optional_list(source.get("entities"))
        record.custom_emoji_ids = optional_list(source.get("custom_emoji_ids"))
        record.raw_payload = optional_dict(source.get("raw_payload"))
        record.source_metadata = optional_dict(source.get("metadata"))
        await self.session.flush()
        await touch_content_objects(self.session, [content_object_id])

    async def decide_deferred_link_snapshots(
        self, content_object: ContentObject, *, decision: str
    ) -> None:
        status = "rejected" if decision == "reject" else "accepted"
        async with storage_transaction(self.session, self.storage) as writes:
            if status == "accepted":
                remaining = remaining_text_link_urls(content_object)
                start = len(link_asset_urls(content_object)) + 1
                for index, url in enumerate(remaining, start=start):
                    await self._link_asset(
                        writes, content_object, url=url, filename=f"link-{index}.url"
                    )
                if remaining:
                    content_object.updated_at = datetime.now(UTC)
                    self._publish(content_object, "content.object.updated")
            record = await self.session.get(ContentLinkSnapshotDecision, content_object.id)
            if record is None:
                self.session.add(
                    ContentLinkSnapshotDecision(
                        content_object_id=content_object.id,
                        owner_user_id=content_object.owner_user_id,
                        status=status,
                    )
                )
            else:
                record.status = status
            await touch_content_objects(self.session, [content_object.id])
            await self.session.commit()

    # --- collections ------------------------------------------------------------------

    async def merge_notes(
        self,
        *,
        owner_user_id: str,
        target: ContentObject,
        source_slugs: list[str],
        title: str | None,
    ) -> str:
        unique_slugs = [slug for slug in dict.fromkeys(source_slugs) if slug != target.slug]
        sources = await self.repository.list_by_slugs(
            owner_user_id=owner_user_id, slugs=unique_slugs
        )
        if len(sources) != len(unique_slugs):
            raise NoteNotFoundError
        by_slug = {source.slug: source for source in sources}
        collection = await self._ensure_collection(target, title=title)
        assignment = await self._current_assignment(collection)
        position = await self.repository.next_collection_position(collection.id)
        touched = [collection.id]
        for slug in unique_slugs:
            source = by_slug[slug]
            previous = await self.repository.get_membership(source.id)
            if previous is not None:
                touched.append(previous.collection_id)
                previous.collection_id = collection.id
                previous.position = position
            else:
                self._add_member(collection, source, position)
            position += 10
            if assignment is not None:
                for object_id in await self.repository.descendant_ids([source.id]):
                    await self.taxonomy.create_manual_assignment(
                        owner_user_id=owner_user_id,
                        content_object_id=object_id,
                        category_id=assignment.category_id,
                        reasoning="Assigned during content merge.",
                        commit=False,
                    )
            touched.append(source.id)
        await self.session.flush()
        await touch_content_objects(self.session, touched)
        self._publish(collection, "content.object.updated")
        await self.session.commit()
        return collection.id

    async def remove_collection_items(
        self, collection: ContentObject, *, item_slugs: list[str]
    ) -> None:
        """Detach items; a collection left with one leaf child collapses into that child
        (its assets move to the collection object, which takes the child's kind)."""
        if collection.kind != "collection":
            raise NoteNotFoundError
        items = await self.repository.list_collection_items(collection.id)
        wanted = set(item_slugs)
        removed = [item for item in items if item.content_object.slug in wanted]
        if not removed:
            return
        remaining = [item for item in items if item not in removed]
        removed_ids = [item.content_object_id for item in removed]
        await self.session.execute(
            delete(ContentCollectionItem).where(
                ContentCollectionItem.id.in_([item.id for item in removed])
            )
        )
        if len(remaining) == 1 and remaining[0].content_object.kind in ("simple", "complex"):
            child = remaining[0].content_object
            asset_ids = [asset.id for asset in child.assets]
            await self.session.execute(
                update(ContentAsset)
                .where(ContentAsset.content_object_id == child.id)
                .values(content_object_id=collection.id)
            )
            await reassign_asset_snapshots(self.session, asset_ids, collection.id)
            await self.session.execute(
                update(ContentObject)
                .where(ContentObject.id == collection.id)
                .values(
                    kind=child.kind,
                    media_type=child.media_type,
                    source_filename=child.source_filename,
                    mime_type=child.mime_type,
                    size_bytes=child.size_bytes,
                )
            )
            # Assets keep their storage keys under the child's prefix; storage cleanup checks
            # for live keys before removing a prefix.
            await self.session.execute(delete(ContentObject).where(ContentObject.id == child.id))
            await record_tombstones(self.session, collection.owner_user_id, [child.id])
        await touch_content_objects(self.session, [collection.id, *removed_ids])
        self._publish(collection, "content.object.updated")
        await self.session.commit()

    async def _ensure_collection(
        self, content_object: ContentObject, *, title: str | None
    ) -> ContentObject:
        """Turn a note into a collection whose first child holds the previous content."""
        if content_object.kind == "collection":
            if title:
                content_object.title = normalize_title(title) or content_object.title
            return content_object
        owner_user_id = content_object.owner_user_id
        assignment = await self._current_assignment(content_object)
        child = ContentObject(
            id=str(uuid4()),
            owner_user_id=owner_user_id,
            slug=await self._unique_slug(owner_user_id, f"{content_object.slug}-item"),
            title=content_object.title,
            kind=content_object.kind,
            media_type=content_object.media_type,
            source_filename=content_object.source_filename,
            mime_type=content_object.mime_type,
            size_bytes=content_object.size_bytes,
            sort_order=content_object.sort_order,
            created_at=content_object.created_at,
        )
        moved_asset_ids = [asset.id for asset in content_object.assets]
        for asset in list(content_object.assets):
            asset.content_object = child
        content_object.title = normalize_title(title) if title else content_object.title
        content_object.kind = "collection"
        content_object.media_type = None
        content_object.source_filename = None
        content_object.mime_type = None
        content_object.size_bytes = None
        self.repository.add(child)
        await self.session.flush()
        await reassign_asset_snapshots(self.session, moved_asset_ids, child.id)
        inherited = (
            await self.tags.list_active_tags_for_contents(
                owner_user_id=owner_user_id, content_object_ids=[content_object.id]
            )
        ).get(content_object.id, [])
        for tag in inherited:
            await self.tags.assign_tag_to_content(
                owner_user_id=owner_user_id,
                content_object_id=child.id,
                tag_id=tag.id,
                assigned_by_user_id=owner_user_id,
                reasoning="Inherited from collection source object.",
                commit=False,
            )
        if assignment is not None:
            await self.taxonomy.create_manual_assignment(
                owner_user_id=owner_user_id,
                content_object_id=child.id,
                category_id=assignment.category_id,
                reasoning="Inherited from collection source object.",
                commit=False,
            )
        self._add_member(content_object, child, 10)
        await self.session.flush()
        return content_object

    # --- helpers ----------------------------------------------------------------------

    async def _new_object(
        self,
        *,
        owner_user_id: str,
        title: str,
        slug_source: str,
        kind: str,
        media_type: str | None,
        source_filename: str | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        object_id: str | None = None,
    ) -> ContentObject:
        obj = ContentObject(
            id=object_id or str(uuid4()),
            owner_user_id=owner_user_id,
            slug=await self._unique_slug(owner_user_id, slug_source),
            title=title,
            kind=kind,
            media_type=media_type,
            source_filename=source_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sort_order=await self.repository.min_sort_order(owner_user_id=owner_user_id) - 10,
            assets=[],
            collection_items=[],
            collection_memberships=[],
        )
        self.repository.add(obj)
        return obj

    async def _text_asset(
        self, writes: StorageWrites, obj: ContentObject, *, text: str, role: str
    ) -> ContentAsset:
        asset_id = str(uuid4())
        key = asset_key(obj.id, asset_id, "content.md")
        stored = await writes.put_bytes(key, _text_file_bytes(obj.title, text), "text/markdown")
        asset = ContentAsset(
            id=asset_id,
            role=role,
            media_type="text",
            filename="content.md",
            mime_type="text/markdown",
            size_bytes=stored.size_bytes,
            storage_key=key,
            checksum=stored.checksum,
            text_content=text,
        )
        obj.assets.append(asset)
        return asset

    async def _link_asset(
        self, writes: StorageWrites, obj: ContentObject, *, url: str, filename: str
    ) -> ContentAsset:
        asset_id = str(uuid4())
        key = asset_key(obj.id, asset_id, filename)
        stored = await writes.put_bytes(key, f"{url}\n".encode(), "text/uri-list")
        asset = ContentAsset(
            id=asset_id,
            role="original",
            media_type="link",
            filename=filename,
            mime_type="text/uri-list",
            size_bytes=stored.size_bytes,
            storage_key=key,
            checksum=stored.checksum,
            text_content=url,
        )
        obj.assets.append(asset)
        return asset

    async def _file_asset(
        self, writes: StorageWrites, obj: ContentObject, source: _FileSource
    ) -> ContentAsset:
        asset_id = str(uuid4())
        key = asset_key(obj.id, asset_id, source.filename)
        if source.upload is not None:
            await writes.move(source.upload.storage_key, key)
            checksum = source.upload.checksum
        elif source.path is not None:
            stored = await writes.put_file(key, source.path, source.content_type)
            checksum = stored.checksum
        else:  # pragma: no cover - constructor invariant
            raise ValueError("file source without data")
        asset = ContentAsset(
            id=asset_id,
            role="original",
            media_type=source.facts.media_type,
            filename=source.filename,
            mime_type=source.content_type,
            size_bytes=source.size_bytes,
            storage_key=key,
            checksum=checksum,
            text_content=source.facts.text_content,
            image_width=source.facts.image_width,
            image_height=source.facts.image_height,
        )
        obj.assets.append(asset)
        return asset

    async def _consume(self, uploads: Sequence[ContentFileUpload]) -> None:
        for upload in uploads:
            await self.session.delete(upload)

    def _add_member(self, collection: ContentObject, child: ContentObject, position: int) -> None:
        self.repository.add_collection_item(
            ContentCollectionItem(collection=collection, content_object=child, position=position)
        )

    async def _finish_new(
        self,
        root: ContentObject,
        children: Sequence[ContentObject],
        *,
        folder_path: str | None,
        tag_names: list[str],
    ) -> None:
        await self.session.flush()
        for obj in (root, *children):
            await self._apply_tags_and_folder(obj, folder_path, tag_names)
            self._publish(obj, "content.object.created")
        logger.info(
            "content.note.created",
            owner_user_id=root.owner_user_id,
            content_object_id=root.id,
            kind=root.kind,
            media_type=root.media_type,
            children=len(children),
        )

    async def _apply_tags_and_folder(
        self, obj: ContentObject, folder_path: str | None, tag_names: list[str]
    ) -> None:
        if tag_names:
            await self.tags.replace_manual_tags_for_content(
                owner_user_id=obj.owner_user_id,
                content_object_id=obj.id,
                tag_names=tag_names,
                assigned_by_user_id=obj.owner_user_id,
            )
        await self.taxonomy.assign_content_to_path(
            owner_user_id=obj.owner_user_id,
            content_object_id=obj.id,
            raw_path=folder_path,
            reasoning=FOLDER_REASONING,
            commit=False,
        )

    async def _current_assignment(self, obj: ContentObject) -> TaxonomyContentAssignment | None:
        value: TaxonomyContentAssignment | None = await self.session.scalar(
            select(TaxonomyContentAssignment).where(
                TaxonomyContentAssignment.content_object_id == obj.id,
                TaxonomyContentAssignment.is_current.is_(True),
            )
        )
        return value

    async def _unique_slug(self, owner_user_id: str, source: str) -> str:
        base = slugify(source)
        await self.repository.lock_slug_base(owner_user_id=owner_user_id, slug_base=base)
        escaped = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        taken = set(
            await self.session.scalars(
                select(ContentObject.slug).where(
                    ContentObject.owner_user_id == owner_user_id,
                    (ContentObject.slug == base)
                    | ContentObject.slug.like(f"{escaped}-%", escape="\\"),
                )
            )
        )
        if base not in taken:
            return base
        counter = 2
        while f"{base}-{counter}" in taken:
            counter += 1
        return f"{base}-{counter}"

    def _publish(self, obj: ContentObject, event_name: str) -> None:
        self.events.publish(
            EventEnvelope.new(
                event_name=event_name,  # type: ignore[arg-type]
                entity_id=obj.id,
                correlation_id=str(uuid4()),
                user_id=obj.owner_user_id,
                payload=ContentObjectChangedPayload(
                    content_object_id=obj.id,
                    asset_ids=[asset.id for asset in obj.assets],
                    metadata={"kind": obj.kind, "media_type": obj.media_type},
                ),
            )
        )


def _text_file_bytes(title: str, text: str) -> bytes:
    return f"# {title}\n\n{text}\n".encode()
