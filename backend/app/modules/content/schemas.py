from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.search.schemas import SearchContentMatch

ContentKind = Literal["simple", "complex", "collection"]
ContentMediaType = Literal["text", "image", "audio", "video", "link", "document"]
SnapshotViewKind = Literal["webpage_html", "pdf", "markdown"]
NoteSort = Literal["newest", "custom"]


class TagResponse(BaseModel):
    id: str
    name: str
    slug: str
    count: int = 0


class FolderResponse(BaseModel):
    id: str
    name: str
    slug: str
    path: str
    direct_count: int = 0
    total_count: int = 0


class ContentTaxonomyCategoryResponse(BaseModel):
    id: str
    name: str
    slug: str
    path: str


class FolderTreeItem(FolderResponse):
    children: list[FolderTreeItem] = Field(default_factory=list)


class FolderTreeResponse(BaseModel):
    items: list[FolderTreeItem]


class CollectionParentResponse(BaseModel):
    id: str
    slug: str
    title: str


class SnapshotViewResponse(BaseModel):
    kind: SnapshotViewKind
    label: str
    url: str


class SourceMetadataResponse(BaseModel):
    provider: str
    provider_label: str
    external_id: str
    url: str | None = None
    title: str | None = None
    original_created_at: datetime | None = None
    origin: dict[str, Any] | None = None
    author: dict[str, Any] | None = None
    group_id: str | None = None
    entities: list[dict[str, Any]] = Field(default_factory=list)
    custom_emoji_ids: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NoteAssetResponse(BaseModel):
    id: str
    role: str
    media_type: ContentMediaType
    filename: str
    mime_type: str | None
    size_bytes: int
    url: str | None = None
    text_content: str | None = None
    thumbnail_url: str | None = None
    thumbnail_text: str | None = None
    markdown_url: str | None = None
    pdf_url: str | None = None
    html_url: str | None = None
    snapshot_views: list[SnapshotViewResponse] = Field(default_factory=list)
    image_width: int | None = None
    image_height: int | None = None
    source: SourceMetadataResponse | None = None


class NoteCardResponse(BaseModel):
    id: str
    slug: str
    kind: ContentKind
    media_type: ContentMediaType | None
    title: str
    source_filename: str | None
    taxonomy_category: ContentTaxonomyCategoryResponse | None
    tags: list[TagResponse]
    is_favorite: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime
    download_url: str
    collection: CollectionParentResponse | None = None
    source: SourceMetadataResponse | None = None
    search_matches: list[SearchContentMatch] = Field(default_factory=list)
    assets: list[NoteAssetResponse] = Field(default_factory=list)
    items: list[NoteCardResponse] = Field(default_factory=list)


class NoteListResponse(BaseModel):
    items: list[NoteCardResponse]


class CreateNoteRequest(BaseModel):
    media_type: ContentMediaType | None = None
    text: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, max_length=512)
    folder_path: str | None = Field(default=None, max_length=1024)
    tag_names: list[str] = Field(default_factory=list)
    file_upload_ids: list[str] = Field(default_factory=list)


class UploadedFileResponse(BaseModel):
    id: str
    source_filename: str
    media_type: ContentMediaType
    mime_type: str | None
    size_bytes: int
    expires_at: datetime


class FileUploadResponse(BaseModel):
    files: list[UploadedFileResponse]
    object: NoteCardResponse | None


class UpdateNoteRequest(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    tag_names: list[str] | None = None


class FavoriteNoteRequest(BaseModel):
    is_favorite: bool


class ReorderNoteItem(BaseModel):
    slug: str
    position: int


class ReorderNotesRequest(BaseModel):
    items: list[ReorderNoteItem] = Field(min_length=1)


class BulkDeleteRequest(BaseModel):
    slugs: list[str] = Field(min_length=1)


class RemoveCollectionItemsRequest(BaseModel):
    item_slugs: list[str] = Field(min_length=1)


class MergeNotesRequest(BaseModel):
    target_slug: str
    source_slugs: list[str] = Field(min_length=1)
    title: str | None = Field(default=None, max_length=512)


class FolderDetailResponse(BaseModel):
    folder: FolderResponse
    tags: list[TagResponse]
    notes: list[NoteCardResponse]
