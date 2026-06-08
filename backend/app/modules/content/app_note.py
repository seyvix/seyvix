"""Web-facing note JSON.

Uses camelCase and flattened ``objects`` matching the SPA contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.content.schemas import (
    FileUploadResponse,
    FolderResponse,
    NoteAssetResponse,
    NoteCardResponse,
    SnapshotViewResponse,
    TagResponse,
    UploadedFileResponse,
)
from app.modules.search.schemas import SearchContentMatch

NoteObjectType = Literal["text", "image", "link", "document", "audio", "video"]
NoteAppKind = Literal["simple", "composite", "collection"]


class AppSnapshotView(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    kind: str
    label: str
    url: str


class AppSourceMetadata(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    provider: str
    providerLabel: str = Field(serialization_alias="providerLabel")
    externalId: str = Field(serialization_alias="externalId")
    url: str | None = None
    title: str | None = None
    originalCreatedAt: datetime | None = Field(
        default=None,
        serialization_alias="originalCreatedAt",
    )
    origin: dict[str, Any] | None = None
    author: dict[str, Any] | None = None
    groupId: str | None = Field(default=None, serialization_alias="groupId")
    entities: list[dict[str, Any]] = Field(default_factory=list)
    customEmojiIds: list[str] = Field(
        default_factory=list,
        serialization_alias="customEmojiIds",
    )
    rawPayload: dict[str, Any] | None = Field(default=None, serialization_alias="rawPayload")
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppTag(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    id: str
    name: str
    slug: str


class AppTaxonomyCategory(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    id: str
    name: str
    slug: str
    path: str


class AppCollectionParent(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    id: str
    slug: str
    title: str


class AppDeferredLinkSnapshots(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    totalLinks: int = Field(serialization_alias="totalLinks")
    processedLinks: int = Field(serialization_alias="processedLinks")
    remainingLinks: int = Field(serialization_alias="remainingLinks")
    expiresAt: datetime = Field(serialization_alias="expiresAt")
    status: str


class AppNoteObject(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    id: str
    noteId: str | None = None
    object_type: NoteObjectType = Field(serialization_alias="type")
    content: str
    caption: str | None = None
    cover: str | None = None
    thumbnailUrl: str | None = None
    thumbnailText: str | None = None
    imageWidth: int | None = None
    imageHeight: int | None = None
    visualWidth: int | None = None
    visualHeight: int | None = None
    snapshotViews: list[AppSnapshotView] = Field(default_factory=list)
    filename: str | None = None
    mimeType: str | None = None
    sizeBytes: int | None = None
    slug: str | None = None
    source: AppSourceMetadata | None = None
    createdAt: datetime = Field(serialization_alias="createdAt")


class AppNote(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    id: str
    slug: str
    note_kind: NoteAppKind = Field(serialization_alias="type")
    title: str
    cover: str | None = None
    tags: list[AppTag] = Field(default_factory=list)
    taxonomyCategory: AppTaxonomyCategory | None = Field(
        default=None,
        serialization_alias="taxonomyCategory",
    )
    folderId: str | None = Field(default=None, serialization_alias="folderId")
    objects: list[AppNoteObject] = Field(default_factory=list)
    createdAt: datetime = Field(serialization_alias="createdAt")
    updatedAt: datetime = Field(serialization_alias="updatedAt")
    isFavorite: bool = Field(default=False, serialization_alias="isFavorite")
    collection: AppCollectionParent | None = None
    source: AppSourceMetadata | None = None
    deferredLinkSnapshots: AppDeferredLinkSnapshots | None = Field(
        default=None,
        serialization_alias="deferredLinkSnapshots",
    )
    searchMatches: list[SearchContentMatch] = Field(
        default_factory=list,
        serialization_alias="searchMatches",
    )


class AppNoteListResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    items: list[AppNote]
    nextOffset: int | None = Field(default=None, serialization_alias="nextOffset")


class AppCardNoteObject(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    id: str
    noteId: str | None = None
    object_type: NoteObjectType = Field(serialization_alias="type")
    content: str
    cover: str | None = None
    thumbnailUrl: str | None = None
    thumbnailText: str | None = None
    imageWidth: int | None = None
    imageHeight: int | None = None
    visualWidth: int | None = None
    visualHeight: int | None = None
    filename: str | None = None
    mimeType: str | None = None
    sizeBytes: int | None = None
    slug: str | None = None
    createdAt: datetime = Field(serialization_alias="createdAt")


class AppCardNote(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    id: str
    slug: str
    note_kind: NoteAppKind = Field(serialization_alias="type")
    title: str
    tags: list[AppTag] = Field(default_factory=list)
    taxonomyCategory: AppTaxonomyCategory | None = Field(
        default=None,
        serialization_alias="taxonomyCategory",
    )
    folderId: str | None = Field(default=None, serialization_alias="folderId")
    objects: list[AppCardNoteObject] = Field(default_factory=list)
    createdAt: datetime = Field(serialization_alias="createdAt")
    updatedAt: datetime = Field(serialization_alias="updatedAt")
    isFavorite: bool = Field(default=False, serialization_alias="isFavorite")
    collection: AppCollectionParent | None = None
    deferredLinkSnapshots: AppDeferredLinkSnapshots | None = Field(
        default=None,
        serialization_alias="deferredLinkSnapshots",
    )
    searchMatches: list[SearchContentMatch] = Field(
        default_factory=list,
        serialization_alias="searchMatches",
    )


class AppCardNoteListResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    items: list[AppCardNote]
    nextOffset: int | None = Field(default=None, serialization_alias="nextOffset")


class FileUploadAppResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    files: list[UploadedFileResponse]
    object: AppNote | None = None


class FolderDetailAppResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    folder: FolderResponse
    tags: list[TagResponse]
    notes: list[AppNote]


def _snapshots(views: list[SnapshotViewResponse]) -> list[AppSnapshotView]:
    return [AppSnapshotView(kind=v.kind, label=v.label, url=v.url) for v in views]


def _source(
    source: object,
    *,
    include_entities: bool = True,
    include_raw_payload: bool = True,
    include_metadata: bool = True,
) -> AppSourceMetadata | None:
    if source is None:
        return None
    data = source.model_dump() if isinstance(source, BaseModel) else source
    if not isinstance(data, dict):
        return None
    return AppSourceMetadata(
        provider=data["provider"],
        providerLabel=data["provider_label"],
        externalId=data["external_id"],
        url=data.get("url"),
        title=data.get("title"),
        originalCreatedAt=data.get("original_created_at"),
        origin=data.get("origin"),
        author=data.get("author"),
        groupId=data.get("group_id"),
        entities=data.get("entities") or [] if include_entities else [],
        customEmojiIds=data.get("custom_emoji_ids") or [] if include_entities else [],
        rawPayload=data.get("raw_payload") if include_raw_payload else None,
        metadata=data.get("metadata") or {} if include_metadata else {},
    )


def _deferred_link_snapshots(card: NoteCardResponse) -> AppDeferredLinkSnapshots | None:
    value = card.deferred_link_snapshots
    if value is None:
        return None
    return AppDeferredLinkSnapshots(
        totalLinks=value.total_links,
        processedLinks=value.processed_links,
        remainingLinks=value.remaining_links,
        expiresAt=value.expires_at,
        status=value.status,
    )


def _media_to_object_type(media_type: str | None) -> NoteObjectType:
    if media_type in ("text", "image", "link", "audio", "video"):
        return media_type  # type: ignore[return-value]
    return "document"


def _kind_to_app_kind(kind: str) -> NoteAppKind:
    if kind == "complex":
        return "composite"
    if kind == "collection":
        return "collection"
    return "simple"


def _limit_text_content(content: str, limit: int | None) -> str:
    if limit is None or len(content) <= limit:
        return content
    return f"{content[:limit].rstrip()}..."


def _map_asset(
    asset: NoteAssetResponse,
    download_url: str,
    created_at: datetime,
    *,
    text_content_limit: int | None = None,
    include_source: bool = True,
    include_snapshot_views: bool = True,
) -> AppNoteObject:
    ot = _media_to_object_type(asset.media_type)
    if ot in ("text", "link"):
        content = asset.text_content or asset.url or download_url
    else:
        content = asset.url or download_url
    if ot == "text":
        content = _limit_text_content(content, text_content_limit)
    return AppNoteObject(
        id=asset.id,
        object_type=ot,
        content=content,
        thumbnailUrl=asset.thumbnail_url,
        thumbnailText=asset.thumbnail_text,
        imageWidth=asset.image_width,
        imageHeight=asset.image_height,
        visualWidth=asset.image_width,
        visualHeight=asset.image_height,
        snapshotViews=_snapshots(asset.snapshot_views) if include_snapshot_views else [],
        filename=asset.filename,
        mimeType=asset.mime_type,
        sizeBytes=asset.size_bytes,
        source=_source(asset.source) if include_source else None,
        createdAt=created_at,
    )


def _collection_asset_to_object(
    item: NoteCardResponse,
    asset: NoteAssetResponse,
    *,
    text_content_limit: int | None = None,
    include_source: bool = True,
    include_snapshot_views: bool = True,
) -> AppNoteObject:
    obj = _map_asset(
        asset,
        item.download_url,
        item.created_at,
        text_content_limit=text_content_limit,
        include_source=include_source,
        include_snapshot_views=include_snapshot_views,
    )
    obj.noteId = item.id
    obj.slug = item.slug
    if include_source and obj.source is None:
        obj.source = _source(item.source)
    return obj


def _collection_item_to_objects(
    item: NoteCardResponse,
    *,
    text_content_limit: int | None = None,
    include_source: bool = True,
    include_snapshot_views: bool = True,
) -> list[AppNoteObject]:
    if item.assets:
        return [
            _collection_asset_to_object(
                item,
                asset,
                text_content_limit=text_content_limit,
                include_source=include_source,
                include_snapshot_views=include_snapshot_views,
            )
            for asset in item.assets
        ]

    ot = _media_to_object_type(item.media_type)
    content = item.download_url
    if ot == "text":
        content = _limit_text_content(content, text_content_limit)
    return [
        AppNoteObject(
            id=item.id,
            noteId=item.id,
            object_type=ot,
            content=content,
            slug=item.slug,
            source=_source(item.source) if include_source else None,
            createdAt=item.created_at,
        )
    ]


def _compact_search_matches(
    matches: list[SearchContentMatch],
    *,
    max_matches: int,
    text_limit: int,
) -> list[SearchContentMatch]:
    compact: list[SearchContentMatch] = []
    for match in matches[:max_matches]:
        text = match.text.strip()
        if len(text) > text_limit:
            text = f"{text[:text_limit].rstrip()}..."
        compact.append(
            SearchContentMatch(
                chunk_id=match.chunk_id,
                chunk_external_id=match.chunk_external_id,
                text=text,
                score=match.score,
                highlight_ranges=[
                    range_
                    for range_ in match.highlight_ranges
                    if range_.end <= len(text)
                ],
            )
        )
    return compact


def note_card_to_app_note(
    card: NoteCardResponse,
    *,
    text_content_limit: int | None = None,
    include_source: bool = True,
    include_snapshot_views: bool = True,
    max_objects: int | None = None,
    max_search_matches: int | None = None,
    search_match_text_limit: int | None = None,
) -> AppNote:
    if card.kind == "collection":
        objects = [
            obj
            for ch in card.items
            for obj in _collection_item_to_objects(
                ch,
                text_content_limit=text_content_limit,
                include_source=include_source,
                include_snapshot_views=include_snapshot_views,
            )
        ]
    elif card.assets:
        objects = [
            _map_asset(
                a,
                card.download_url,
                card.created_at,
                text_content_limit=text_content_limit,
                include_source=include_source,
                include_snapshot_views=include_snapshot_views,
            )
            for a in card.assets
        ]
    elif card.media_type == "text" or card.media_type is None:
        objects = [
            AppNoteObject(
                id=f"{card.id}-text",
                object_type="text",
                content=_limit_text_content(card.title, text_content_limit),
                source=_source(card.source) if include_source else None,
                createdAt=card.created_at,
            )
        ]
    else:
        objects = []

    if max_objects is not None:
        objects = objects[:max_objects]

    search_matches = card.search_matches
    if max_search_matches is not None or search_match_text_limit is not None:
        search_matches = _compact_search_matches(
            search_matches,
            max_matches=max_search_matches or len(search_matches),
            text_limit=search_match_text_limit or 10_000,
        )

    return AppNote(
        id=card.id,
        slug=card.slug,
        note_kind=_kind_to_app_kind(card.kind),
        title=card.title,
        cover=card.download_url if card.assets else None,
        tags=[AppTag(id=t.id, name=t.name, slug=t.slug) for t in card.tags],
        taxonomyCategory=(
            AppTaxonomyCategory.model_validate(card.taxonomy_category.model_dump())
            if card.taxonomy_category
            else None
        ),
        folderId=card.taxonomy_category.id if card.taxonomy_category else None,
        objects=objects,
        createdAt=card.created_at,
        updatedAt=card.updated_at,
        isFavorite=card.is_favorite,
        collection=(
            AppCollectionParent.model_validate(card.collection.model_dump())
            if card.collection
            else None
        ),
        source=_source(card.source) if include_source else None,
        deferredLinkSnapshots=_deferred_link_snapshots(card),
        searchMatches=search_matches,
    )


def _card_object(obj: AppNoteObject) -> AppCardNoteObject:
    return AppCardNoteObject(
        id=obj.id,
        noteId=obj.noteId,
        object_type=obj.object_type,
        content=obj.content,
        cover=obj.cover,
        thumbnailUrl=obj.thumbnailUrl,
        thumbnailText=obj.thumbnailText,
        imageWidth=obj.imageWidth,
        imageHeight=obj.imageHeight,
        visualWidth=obj.visualWidth,
        visualHeight=obj.visualHeight,
        filename=obj.filename,
        mimeType=obj.mimeType,
        sizeBytes=obj.sizeBytes,
        slug=obj.slug,
        createdAt=obj.createdAt,
    )


def note_card_to_app_card_note(
    card: NoteCardResponse,
    *,
    text_content_limit: int,
    max_objects: int = 6,
    max_search_matches: int = 1,
    search_match_text_limit: int = 240,
) -> AppCardNote:
    note = note_card_to_app_note(
        card,
        text_content_limit=text_content_limit,
        include_source=False,
        include_snapshot_views=False,
        max_objects=max_objects,
        max_search_matches=max_search_matches,
        search_match_text_limit=search_match_text_limit,
    )
    return AppCardNote(
        id=note.id,
        slug=note.slug,
        note_kind=note.note_kind,
        title=note.title,
        tags=note.tags,
        taxonomyCategory=note.taxonomyCategory,
        folderId=note.folderId,
        objects=[_card_object(obj) for obj in note.objects],
        createdAt=note.createdAt,
        updatedAt=note.updatedAt,
        isFavorite=note.isFavorite,
        collection=note.collection,
        deferredLinkSnapshots=note.deferredLinkSnapshots,
        searchMatches=note.searchMatches,
    )


def upload_result_to_json_bytes(result: NoteCardResponse | FileUploadResponse) -> bytes:
    if isinstance(result, FileUploadResponse):
        wrapped = FileUploadAppResponse(
            files=result.files,
            object=note_card_to_app_note(result.object) if result.object else None,
        )
        return wrapped.model_dump_json(by_alias=True).encode("utf-8")
    return note_card_to_app_note(result).model_dump_json(by_alias=True).encode("utf-8")
