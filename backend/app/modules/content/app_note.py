"""Web-facing note JSON: camelCase + flattened ``objects`` (same contract the SPA used via ``mapBackendNote``)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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

NoteObjectType = Literal["text", "image", "link", "document", "audio", "video"]
NoteAppKind = Literal["simple", "composite", "collection"]


class AppSnapshotView(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    kind: str
    label: str
    url: str


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


class AppNoteObject(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    id: str
    object_type: NoteObjectType = Field(serialization_alias="type")
    content: str
    cover: str | None = None
    thumbnailUrl: str | None = None
    thumbnailText: str | None = None
    imageWidth: int | None = None
    imageHeight: int | None = None
    snapshotViews: list[AppSnapshotView] = Field(default_factory=list)
    filename: str | None = None
    mimeType: str | None = None
    sizeBytes: int | None = None
    slug: str | None = None
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


class AppNoteListResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    items: list[AppNote]


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


def _map_asset(asset: NoteAssetResponse, download_url: str, created_at: datetime) -> AppNoteObject:
    ot = _media_to_object_type(asset.media_type)
    if ot in ("text", "link"):
        content = asset.text_content or asset.url or download_url
    else:
        content = asset.url or download_url
    return AppNoteObject(
        id=asset.id,
        object_type=ot,
        content=content,
        thumbnailUrl=asset.thumbnail_url,
        thumbnailText=asset.thumbnail_text,
        imageWidth=asset.image_width,
        imageHeight=asset.image_height,
        snapshotViews=_snapshots(asset.snapshot_views),
        filename=asset.filename,
        mimeType=asset.mime_type,
        sizeBytes=asset.size_bytes,
        createdAt=created_at,
    )


def _collection_item_to_object(item: NoteCardResponse) -> AppNoteObject:
    first = item.assets[0] if item.assets else None
    ot = _media_to_object_type(first.media_type if first else item.media_type)
    if ot in ("text", "link"):
        tc = first.text_content if first else None
        url = first.url if first else None
        content = tc or url or item.download_url
    else:
        content = (first.url if first else None) or item.download_url
    thumb = None
    if ot in ("document", "link") and first is not None:
        thumb = first.thumbnail_url
    cover = None if ot == "document" else (first.url if first else None)
    snaps = _snapshots(first.snapshot_views) if first is not None else []
    return AppNoteObject(
        id=item.id,
        object_type=ot,
        content=content,
        cover=cover,
        thumbnailUrl=thumb,
        thumbnailText=first.thumbnail_text if first else None,
        imageWidth=first.image_width if first else None,
        imageHeight=first.image_height if first else None,
        snapshotViews=snaps,
        slug=item.slug,
        filename=first.filename if first else None,
        mimeType=first.mime_type if first else None,
        sizeBytes=first.size_bytes if first else None,
        createdAt=item.created_at,
    )


def note_card_to_app_note(card: NoteCardResponse) -> AppNote:
    if card.kind == "collection":
        objects = [_collection_item_to_object(ch) for ch in card.items]
    elif card.assets:
        objects = [_map_asset(a, card.download_url, card.created_at) for a in card.assets]
    elif card.media_type == "text" or card.media_type is None:
        objects = [
            AppNoteObject(
                id=f"{card.id}-text",
                object_type="text",
                content=card.title,
                createdAt=card.created_at,
            )
        ]
    else:
        objects = []

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
    )


def upload_result_to_json_bytes(result: NoteCardResponse | FileUploadResponse) -> bytes:
    if isinstance(result, FileUploadResponse):
        wrapped = FileUploadAppResponse(
            files=result.files,
            object=note_card_to_app_note(result.object) if result.object else None,
        )
        return wrapped.model_dump_json(by_alias=True).encode("utf-8")
    return note_card_to_app_note(result).model_dump_json(by_alias=True).encode("utf-8")
