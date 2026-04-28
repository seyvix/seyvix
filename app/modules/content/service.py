from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.content.infrastructure.repositories import (
    CategoryRepository,
    ContentRepository,
    FileUploadRepository,
    TagRepository,
)
from app.modules.content.models import (
    ContentAsset,
    ContentCategory,
    ContentCollectionItem,
    ContentFileUpload,
    ContentObject,
    ContentTag,
)
from app.modules.content.schemas import (
    CollectionParentResponse,
    FileUploadResponse,
    FolderDetailResponse,
    FolderResponse,
    FolderTreeItem,
    FolderTreeResponse,
    NoteAssetResponse,
    NoteCardResponse,
    NoteListResponse,
    TagResponse,
    UploadedFileResponse,
)
from app.core.logging import get_logger
from app.modules.content.storage import ContentStorage, slugify

logger = get_logger(__name__)

# Keeps strong references to background asyncio tasks so the GC doesn't collect them
# before they finish (Python docs: "save a reference to the result of create_task").
_background_tasks: set[asyncio.Task[None]] = set()


class NoteNotFoundError(Exception):
    pass


class FolderNotFoundError(Exception):
    pass


class ThumbnailPendingError(Exception):
    pass


@dataclass(slots=True)
class UploadedContent:
    filename: str
    content_type: str | None
    data: bytes


class ContentService:
    def __init__(self, session: AsyncSession, storage_root: Path | None = None) -> None:
        self.session = session
        self.content = ContentRepository(session)
        self.categories = CategoryRepository(session)
        self.tags = TagRepository(session)
        self.file_uploads = FileUploadRepository(session)
        self.storage = ContentStorage(storage_root or Path("data/content"))
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

        if media_type in (None, "text") and text is not None:
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
            upload.size_bytes = stored_file.size_bytes
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
        tag_slugs: list[str],
        folder_path: str | None,
        sort: str,
    ) -> NoteListResponse:
        objects = await self.content.list_all(owner_user_id=owner_user_id)
        normalized_search = search.casefold().strip() if search else None
        normalized_tags = {slugify(tag) for tag in tag_slugs}
        items: list[ContentObject] = []

        for content_object in objects:
            if folder_path and (
                content_object.category is None or content_object.category.path != folder_path
            ):
                continue
            if normalized_tags and not normalized_tags.issubset(
                {tag.slug for tag in content_object.tags},
            ):
                continue
            if normalized_search:
                if content_object.kind == "collection":
                    continue
                if not self._matches_search(content_object, normalized_search):
                    continue
                items.append(content_object)
                continue
            if content_object.kind != "collection" and content_object.collection_memberships:
                continue
            items.append(content_object)

        if sort == "custom":
            items.sort(key=lambda item: (item.sort_order, item.created_at))
        else:
            items.sort(key=lambda item: item.created_at, reverse=True)

        return NoteListResponse(items=[await self._to_card(item) for item in items])

    async def get_note(self, *, owner_user_id: str, slug: str) -> NoteCardResponse:
        return await self._to_card(await self._load_note(owner_user_id=owner_user_id, slug=slug))

    async def get_download_path(self, *, owner_user_id: str, slug: str) -> Path:
        content_object = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        return self.storage.build_archive(content_object)

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
            raise NoteNotFoundError
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
            content_object.title = title
        if tag_names is not None:
            content_object.tags = await self._get_or_create_tags(owner_user_id, tag_names)
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
        next_position = await self._next_collection_position(collection)
        for slug in unique_source_slugs:
            source = by_slug[slug]
            if source.kind == "collection":
                source_items = await self.content.list_collection_items(source.id)
                for item in source_items:
                    item.collection = collection
                    item.position = next_position
                    next_position += 10
                continue
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

    async def delete_notes(self, *, owner_user_id: str, slugs: list[str]) -> None:
        objects = await self.content.list_by_slugs(
            owner_user_id=owner_user_id,
            slugs=slugs,
        )
        # Collect all objects to delete, including nested collection items
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

        # Remove storage directories first
        for obj in to_delete.values():
            self.storage.remove_directory(obj)

        # Bulk DELETE via raw SQL — avoids ORM cascade conflicts when both
        # a collection and its items are deleted in the same session.
        # DB-level ondelete="CASCADE" on ContentCollectionItem and ContentAsset
        # handles join/asset row cleanup automatically.
        await self.session.execute(
            sql_delete(ContentObject).where(ContentObject.id.in_(list(to_delete.keys())))
        )
        await self.session.commit()

    async def list_folders(self, *, owner_user_id: str) -> FolderTreeResponse:
        categories = await self.categories.list_all(owner_user_id=owner_user_id)
        by_id: dict[str, FolderTreeItem] = {
            category.id: self._folder_tree_item(category) for category in categories
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
        category = await self.categories.get_by_path(owner_user_id=owner_user_id, path=folder_path)
        if category is None:
            raise FolderNotFoundError
        notes = await self.list_notes(
            owner_user_id=owner_user_id,
            search=None,
            tag_slugs=[],
            folder_path=folder_path,
            sort="newest",
        )
        tags = sorted(
            {
                tag.slug: tag
                for note in await self.content.list_all(owner_user_id=owner_user_id)
                if note.category is not None and note.category.path == folder_path
                for tag in note.tags
            }.values(),
            key=lambda tag: tag.name.casefold(),
        )
        return FolderDetailResponse(
            folder=self._folder_response(category),
            tags=[self._tag_response(tag) for tag in tags],
            notes=notes.items,
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
        normalized_title = title or text.strip().splitlines()[0][:80]
        category = await self._get_or_create_category(owner_user_id, folder_path)
        tags = await self._get_or_create_tags(owner_user_id, tag_names)
        slug = await self._unique_slug(owner_user_id, normalized_title)
        sort_order = await self.content.get_max_sort_order(owner_user_id=owner_user_id) + 10
        directory = self.storage.object_directory(
            owner_user_id=owner_user_id,
            folder_path=category.path if category else None,
            slug=slug,
            kind="simple",
        )
        stored_file = self.storage.write_text_object(
            directory=directory,
            title=normalized_title,
            text=text,
        )
        content_object = ContentObject(
            owner_user_id=owner_user_id,
            category=category,
            slug=slug,
            title=normalized_title,
            kind="simple",
            media_type="text",
            source_filename=stored_file.filename,
            mime_type="text/markdown",
            size_bytes=stored_file.size_bytes,
            storage_path=directory.relative_to(self.storage.root).as_posix(),
            sort_order=sort_order,
            tags=tags,
        )
        content_object.assets.append(
            ContentAsset(
                role="original",
                media_type="text",
                filename=stored_file.filename,
                mime_type="text/markdown",
                size_bytes=stored_file.size_bytes,
                storage_path=stored_file.relative_path,
                text_content=text,
            ),
        )
        self.content.add(content_object)
        await self.session.commit()
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
        category = await self._get_or_create_category(owner_user_id, folder_path)
        tags = await self._get_or_create_tags(owner_user_id, tag_names)
        file_media_type = self._media_type(uploaded.filename, uploaded.content_type)
        normalized_title = title or text.strip().splitlines()[0][:80] or uploaded.filename
        slug = await self._unique_slug(owner_user_id, normalized_title)
        sort_order = await self.content.get_max_sort_order(owner_user_id=owner_user_id) + 10
        directory = self.storage.object_directory(
            owner_user_id=owner_user_id,
            folder_path=category.path if category else None,
            slug=slug,
            kind="complex",
        )
        stored_file = self.storage.write_binary_object(
            directory=directory,
            filename=uploaded.filename,
            data=uploaded.data,
        )
        stored_text = self.storage.write_text_object(
            directory=directory,
            title=normalized_title,
            text=text,
        )
        content_object = ContentObject(
            owner_user_id=owner_user_id,
            category=category,
            slug=slug,
            title=normalized_title,
            kind="complex",
            media_type=file_media_type,
            source_filename=stored_file.filename,
            mime_type=uploaded.content_type,
            size_bytes=stored_file.size_bytes,
            storage_path=directory.relative_to(self.storage.root).as_posix(),
            sort_order=sort_order,
            tags=tags,
        )
        content_object.assets.append(
            ContentAsset(
                role="original",
                media_type=file_media_type,
                filename=stored_file.filename,
                mime_type=uploaded.content_type,
                size_bytes=stored_file.size_bytes,
                storage_path=stored_file.relative_path,
            ),
        )
        content_object.assets.append(
            ContentAsset(
                role="text",
                media_type="text",
                filename=stored_text.filename,
                mime_type="text/markdown",
                size_bytes=stored_text.size_bytes,
                storage_path=stored_text.relative_path,
                text_content=text,
            ),
        )
        self.content.add(content_object)
        await self.session.commit()
        return await self._reload_write_manifest_and_card(owner_user_id=owner_user_id, slug=slug)

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
            for uploaded in files:
                child = await self._create_uploaded_object(
                    owner_user_id=owner_user_id,
                    uploaded=uploaded,
                    folder_path=collection.category.path if collection.category else folder_path,
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
            title=title or "Imported collection",
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
        category = await self._get_or_create_category(owner_user_id, folder_path)
        tags = await self._get_or_create_tags(owner_user_id, tag_names)
        media_type = self._media_type(uploaded.filename, uploaded.content_type)
        kind = "complex" if media_type == "document" else "simple"
        normalized_title = title or uploaded.filename
        slug = await self._unique_slug(
            owner_user_id,
            Path(uploaded.filename).stem or normalized_title,
        )
        sort_order = await self.content.get_max_sort_order(owner_user_id=owner_user_id) + 10
        directory = self.storage.object_directory(
            owner_user_id=owner_user_id,
            folder_path=category.path if category else None,
            slug=slug,
            kind=kind,
        )
        stored_file = self.storage.write_binary_object(
            directory=directory,
            filename=uploaded.filename,
            data=uploaded.data,
        )
        text_content = self._decode_text(uploaded.data) if media_type == "text" else None
        content_object = ContentObject(
            id=object_id or None,
            owner_user_id=owner_user_id,
            category=category,
            slug=slug,
            title=normalized_title,
            kind=kind,
            media_type=media_type,
            source_filename=stored_file.filename,
            mime_type=uploaded.content_type,
            size_bytes=stored_file.size_bytes,
            storage_path=directory.relative_to(self.storage.root).as_posix(),
            sort_order=sort_order,
            tags=tags,
        )
        content_object.assets.append(
            ContentAsset(
                role="original",
                media_type=media_type,
                filename=stored_file.filename,
                mime_type=uploaded.content_type,
                size_bytes=stored_file.size_bytes,
                storage_path=stored_file.relative_path,
                text_content=text_content,
            ),
        )
        self.content.add(content_object)
        return content_object

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
        category = await self._get_or_create_category(owner_user_id, folder_path)
        tags = await self._get_or_create_tags(owner_user_id, tag_names)
        normalized_slug = slug or await self._unique_slug(owner_user_id, title)
        sort_order = await self.content.get_max_sort_order(owner_user_id=owner_user_id) + 10
        directory = self.storage.object_directory(
            owner_user_id=owner_user_id,
            folder_path=category.path if category else None,
            slug=normalized_slug,
            kind="collection",
        )
        directory.mkdir(parents=True, exist_ok=True)
        collection = ContentObject(
            id=object_id or None,
            owner_user_id=owner_user_id,
            category=category,
            slug=normalized_slug,
            title=title,
            kind="collection",
            media_type=None,
            storage_path=directory.relative_to(self.storage.root).as_posix(),
            sort_order=sort_order,
            tags=tags,
        )
        self.content.add(collection)
        return collection

    async def _ensure_collection(
        self,
        content_object: ContentObject,
        *,
        title: str | None,
    ) -> ContentObject:
        if content_object.kind == "collection":
            if title:
                content_object.title = title
            return content_object

        child_slug = await self._unique_slug(
            content_object.owner_user_id,
            f"{content_object.slug}-item",
        )
        child = ContentObject(
            owner_user_id=content_object.owner_user_id,
            category=content_object.category,
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

        collection_dir = self.storage.object_directory(
            owner_user_id=content_object.owner_user_id,
            folder_path=content_object.category.path if content_object.category else None,
            slug=content_object.slug,
            kind="collection",
        )
        collection_dir.mkdir(parents=True, exist_ok=True)
        content_object.title = title or content_object.title
        content_object.kind = "collection"
        content_object.media_type = None
        content_object.source_filename = None
        content_object.mime_type = None
        content_object.size_bytes = None
        content_object.storage_path = collection_dir.relative_to(self.storage.root).as_posix()
        self.content.add(child)
        self.content.add_collection_item(
            ContentCollectionItem(collection=content_object, content_object=child, position=10),
        )
        return content_object

    async def _next_collection_position(self, collection: ContentObject) -> int:
        current_items = await self.content.list_collection_items(collection.id)
        return max((item.position for item in current_items), default=0) + 10

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
        self.storage.write_manifest(
            directory=self.storage.root / loaded.storage_path,
            manifest=self._manifest(loaded, items=items),
        )
        if loaded.kind == "collection":
            for item in items:
                self.storage.write_manifest(
                    directory=self.storage.root / item.storage_path,
                    manifest=self._manifest(item, items=[]),
                )
        # Schedule async thumbnail generation for any document assets
        all_objects = [loaded, *items] if loaded.kind == "collection" else [loaded]
        logger.info(
            "thumbnail.scan",
            slug=loaded.slug,
            object_count=len(all_objects),
            asset_count=sum(len(obj.assets) for obj in all_objects),
        )
        for obj in all_objects:
            for asset in obj.assets:
                if asset.media_type == "document":
                    asset_path = self.storage.root / asset.storage_path
                    thumb_path = self._thumbnail_path(asset_path)
                    if not thumb_path.exists():
                        task = asyncio.create_task(
                            self._generate_thumbnail_async(asset_path, thumb_path)
                        )
                        _background_tasks.add(task)
                        task.add_done_callback(_background_tasks.discard)
        return await self._to_card(loaded)

    def _thumbnail_path(self, asset_path: Path) -> Path:
        """Returns the path where the thumbnail image for an asset should be stored."""
        thumb_dir = asset_path.parent / "thumbnails"
        return thumb_dir / f"{asset_path.stem}.jpg"

    @staticmethod
    def _render_pdf_thumbnail(asset_path: Path, thumb_path: Path) -> None:
        """Renders the top half of the first page of a PDF as a JPEG thumbnail (sync, blocking)."""
        log = get_logger(__name__)
        log.info("thumbnail.render.start", asset=str(asset_path), thumb=str(thumb_path))
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError:
            log.warning("thumbnail.render.skip", reason="pymupdf not installed")
            return
        try:
            doc = fitz.open(str(asset_path))
            if doc.page_count == 0:
                log.warning("thumbnail.render.skip", reason="empty document", asset=str(asset_path))
                return
            page = doc[0]
            # Crop to top half
            rect = page.rect
            clip = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + rect.height / 2)
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for decent resolution
            pix = page.get_pixmap(matrix=mat, clip=clip)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            # Convert to JPEG via PIL if available, otherwise save directly
            try:
                from PIL import Image  # type: ignore[import-untyped]
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80, optimize=True)
                thumb_path.write_bytes(buf.getvalue())
            except ImportError:
                pix.save(str(thumb_path))
            log.info(
                "thumbnail.render.done",
                asset=str(asset_path),
                thumb=str(thumb_path),
                size_bytes=thumb_path.stat().st_size,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("thumbnail.render.error", asset=str(asset_path), error=str(exc), exc_info=True)

    async def _generate_thumbnail_async(self, asset_path: Path, thumb_path: Path) -> None:
        """Runs PDF thumbnail generation in a thread pool executor."""
        logger.info("thumbnail.scheduled", asset=str(asset_path))
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._render_pdf_thumbnail, asset_path, thumb_path)

    async def get_asset_thumbnail(
        self, *, owner_user_id: str, slug: str, asset_id: str
    ) -> Path:
        """Returns path to thumbnail JPEG, or raises ThumbnailPendingError if not ready yet."""
        content_object = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        asset = next((a for a in content_object.assets if a.id == asset_id), None)
        if asset is None:
            raise NoteNotFoundError
        asset_path = self.storage.root / asset.storage_path
        thumb_path = self._thumbnail_path(asset_path)
        if not thumb_path.exists():
            raise ThumbnailPendingError
        return thumb_path

    async def _get_or_create_category(
        self,
        owner_user_id: str,
        folder_path: str | None,
    ) -> ContentCategory | None:
        if not folder_path:
            return None
        segments = [slugify(segment) for segment in folder_path.split("/") if segment.strip()]
        if not segments:
            return None

        parent: ContentCategory | None = None
        current_path = ""
        for segment in segments:
            current_path = f"{current_path}/{segment}".strip("/")
            category = await self.categories.get_by_path(
                owner_user_id=owner_user_id,
                path=current_path,
            )
            if category is None:
                category = ContentCategory(
                    owner_user_id=owner_user_id,
                    parent=parent,
                    name=segment,
                    slug=segment,
                    path=current_path,
                )
                self.categories.add(category)
                await self.session.flush()
            parent = category
        return parent

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

    async def _get_or_create_tags(
        self, owner_user_id: str, tag_names: list[str]
    ) -> list[ContentTag]:
        tags: list[ContentTag] = []
        seen: set[str] = set()
        for raw_name in tag_names:
            name = raw_name.strip()
            if not name:
                continue
            slug = slugify(name)
            if slug in seen:
                continue
            seen.add(slug)
            tag = await self.tags.get_by_slug(owner_user_id=owner_user_id, slug=slug)
            if tag is None:
                tag = ContentTag(owner_user_id=owner_user_id, name=name, slug=slug)
                self.tags.add(tag)
                await self.session.flush()
            tags.append(tag)
        return tags

    async def _unique_slug(self, owner_user_id: str, title: str) -> str:
        base = slugify(title)
        candidate = base
        counter = 2
        while await self.content.slug_exists(owner_user_id=owner_user_id, slug=candidate):
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    async def _load_note(self, *, owner_user_id: str, slug: str) -> ContentObject:
        content_object = await self.content.get_by_slug(owner_user_id=owner_user_id, slug=slug)
        if content_object is None:
            raise NoteNotFoundError
        return content_object

    async def _to_card(self, content_object: ContentObject) -> NoteCardResponse:
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
        return NoteCardResponse(
            id=content_object.id,
            slug=content_object.slug,
            kind=content_object.kind,  # type: ignore[arg-type]
            media_type=content_object.media_type,  # type: ignore[arg-type]
            title=content_object.title,
            source_filename=content_object.source_filename,
            folder=(
                self._folder_response(content_object.category)
                if content_object.category is not None
                else None
            ),
            tags=[self._tag_response(tag) for tag in content_object.tags],
            is_favorite=content_object.is_favorite,
            sort_order=content_object.sort_order,
            created_at=content_object.created_at,
            updated_at=content_object.updated_at,
            download_url=f"{self.api_prefix}/notes/{content_object.slug}/download",
            collection=collection_parent,
            assets=[
                NoteAssetResponse(
                    id=asset.id,
                    role=asset.role,
                    media_type=asset.media_type,  # type: ignore[arg-type]
                    filename=asset.filename,
                    mime_type=asset.mime_type,
                    size_bytes=asset.size_bytes,
                    url=f"{self.api_prefix}/notes/{content_object.slug}/asset/{asset.id}",
                    text_content=asset.text_content,
                    thumbnail_url=(
                        f"{self.api_prefix}/notes/{content_object.slug}/asset/{asset.id}/thumbnail"
                        if asset.media_type == "document"
                        and self._thumbnail_path(
                            self.storage.root / asset.storage_path
                        ).exists()
                        else None
                    ),
                )
                for asset in content_object.assets
            ],
            items=items,
        )

    def _manifest(
        self,
        content_object: ContentObject,
        *,
        items: list[ContentObject],
    ) -> dict[str, object]:
        return {
            "id": content_object.id,
            "slug": content_object.slug,
            "kind": content_object.kind,
            "media_type": content_object.media_type,
            "title": content_object.title,
            "source_filename": content_object.source_filename,
            "folder": content_object.category.path if content_object.category else None,
            "tags": [tag.slug for tag in content_object.tags],
            "items": [item.slug for item in items],
        }

    @staticmethod
    def _matches_search(content_object: ContentObject, search: str) -> bool:
        haystack = [
            content_object.title,
            content_object.source_filename or "",
            *(asset.text_content or "" for asset in content_object.assets),
        ]
        return any(search in value.casefold() for value in haystack)

    @staticmethod
    def _folder_response(category: ContentCategory) -> FolderResponse:
        return FolderResponse(
            id=category.id,
            name=category.name,
            slug=category.slug,
            path=category.path,
        )

    @staticmethod
    def _folder_tree_item(category: ContentCategory) -> FolderTreeItem:
        return FolderTreeItem(
            id=category.id,
            name=category.name,
            slug=category.slug,
            path=category.path,
            children=[],
        )

    @staticmethod
    def _tag_response(tag: ContentTag) -> TagResponse:
        return TagResponse(id=tag.id, name=tag.name, slug=tag.slug)

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
    def _decode_text(data: bytes) -> str | None:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None
