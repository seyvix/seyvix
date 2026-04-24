from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.content.infrastructure.repositories import (
    CategoryRepository,
    ContentRepository,
    TagRepository,
)
from app.modules.content.models import (
    ContentAsset,
    ContentCategory,
    ContentCollectionItem,
    ContentObject,
    ContentTag,
)
from app.modules.content.schemas import (
    CollectionParentResponse,
    FolderDetailResponse,
    FolderResponse,
    FolderTreeItem,
    FolderTreeResponse,
    NoteAssetResponse,
    NoteCardResponse,
    NoteListResponse,
    TagResponse,
)
from app.modules.content.storage import ContentStorage, slugify


class NoteNotFoundError(Exception):
    pass


class FolderNotFoundError(Exception):
    pass


class CollectionMergeConflictError(Exception):
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
        self.storage = ContentStorage(storage_root or Path("data/content"))
        self.api_prefix = get_settings().api_prefix

    async def create_text_note(
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
        loaded = await self._load_note(owner_user_id=owner_user_id, slug=slug)
        self.storage.write_manifest(
            directory=directory,
            manifest=self._manifest(loaded, items=[]),
        )
        return await self._to_card(loaded)

    async def upload_files(
        self,
        *,
        owner_user_id: str,
        files: list[UploadedContent],
        title: str | None,
        folder_path: str | None,
        tag_names: list[str],
    ) -> NoteCardResponse:
        if len(files) == 1:
            uploaded = files[0]
            content_object = await self._create_uploaded_object(
                owner_user_id=owner_user_id,
                uploaded=uploaded,
                folder_path=folder_path,
                tag_names=tag_names,
            )
            await self.session.commit()
            loaded = await self._load_note(owner_user_id=owner_user_id, slug=content_object.slug)
            self.storage.write_manifest(
                directory=self.storage.root / loaded.storage_path,
                manifest=self._manifest(loaded, items=[]),
            )
            return await self._to_card(loaded)

        collection_title = title or "Imported collection"
        collection = await self._create_collection(
            owner_user_id=owner_user_id,
            title=collection_title,
            folder_path=folder_path,
            tag_names=tag_names,
        )
        child_objects: list[ContentObject] = []
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
            child_objects.append(child)

        await self.session.commit()
        for child in child_objects:
            loaded_child = await self._load_note(owner_user_id=owner_user_id, slug=child.slug)
            self.storage.write_manifest(
                directory=self.storage.root / loaded_child.storage_path,
                manifest=self._manifest(loaded_child, items=[]),
            )
        loaded = await self._load_note(owner_user_id=owner_user_id, slug=collection.slug)
        loaded_items = [
            item.content_object for item in await self.content.list_collection_items(loaded.id)
        ]
        self.storage.write_manifest(
            directory=self.storage.root / loaded.storage_path,
            manifest=self._manifest(loaded, items=loaded_items),
        )
        return await self._to_card(loaded)

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

    async def merge_collection(
        self,
        *,
        owner_user_id: str,
        source_slugs: list[str],
        title: str | None,
    ) -> tuple[NoteCardResponse, int]:
        objects = await self.content.list_by_slugs(owner_user_id=owner_user_id, slugs=source_slugs)
        if len(objects) != len(set(source_slugs)):
            raise NoteNotFoundError

        by_slug = {content_object.slug: content_object for content_object in objects}
        ordered = [by_slug[slug] for slug in source_slugs]
        collections = [
            content_object for content_object in ordered if content_object.kind == "collection"
        ]
        if len(collections) > 1:
            raise CollectionMergeConflictError

        if collections:
            collection = collections[0]
            status_code = 200
            incoming = [
                content_object for content_object in ordered if content_object.kind != "collection"
            ]
        else:
            first_category = ordered[0].category.path if ordered[0].category else None
            collection = await self._create_collection(
                owner_user_id=owner_user_id,
                title=title or "Merged collection",
                folder_path=first_category,
                tag_names=[],
            )
            status_code = 201
            incoming = ordered

        current_items = await self.content.list_collection_items(collection.id)
        next_position = max((item.position for item in current_items), default=0) + 10
        for content_object in incoming:
            if content_object.kind == "collection":
                raise CollectionMergeConflictError
            existing_membership = await self.content.get_membership(content_object.id)
            if existing_membership is not None:
                existing_membership.collection = collection
                existing_membership.position = next_position
            else:
                self.content.add_collection_item(
                    ContentCollectionItem(
                        collection=collection,
                        content_object=content_object,
                        position=next_position,
                    ),
                )
            next_position += 10

        await self.session.commit()
        loaded = await self._load_note(owner_user_id=owner_user_id, slug=collection.slug)
        item_objects = [
            item.content_object for item in await self.content.list_collection_items(loaded.id)
        ]
        self.storage.write_manifest(
            directory=self.storage.root / loaded.storage_path,
            manifest=self._manifest(loaded, items=item_objects),
        )
        return await self._to_card(loaded), status_code

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

    async def _create_uploaded_object(
        self,
        *,
        owner_user_id: str,
        uploaded: UploadedContent,
        folder_path: str | None,
        tag_names: list[str],
    ) -> ContentObject:
        category = await self._get_or_create_category(owner_user_id, folder_path)
        tags = await self._get_or_create_tags(owner_user_id, tag_names)
        media_type = self._media_type(uploaded.filename, uploaded.content_type)
        kind = "complex" if media_type == "document" else "simple"
        title = uploaded.filename
        slug = await self._unique_slug(
            owner_user_id, Path(uploaded.filename).stem or uploaded.filename
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
            owner_user_id=owner_user_id,
            category=category,
            slug=slug,
            title=title,
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
    ) -> ContentObject:
        category = await self._get_or_create_category(owner_user_id, folder_path)
        tags = await self._get_or_create_tags(owner_user_id, tag_names)
        slug = await self._unique_slug(owner_user_id, title)
        sort_order = await self.content.get_max_sort_order(owner_user_id=owner_user_id) + 10
        directory = self.storage.object_directory(
            owner_user_id=owner_user_id,
            folder_path=category.path if category else None,
            slug=slug,
            kind="collection",
        )
        directory.mkdir(parents=True, exist_ok=True)
        collection = ContentObject(
            owner_user_id=owner_user_id,
            category=category,
            slug=slug,
            title=title,
            kind="collection",
            media_type=None,
            storage_path=directory.relative_to(self.storage.root).as_posix(),
            sort_order=sort_order,
            tags=tags,
        )
        self.content.add(collection)
        return collection

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
