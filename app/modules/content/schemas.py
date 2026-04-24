from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ContentKind = Literal["simple", "complex", "collection"]
ContentMediaType = Literal["text", "image", "audio", "video", "link", "document"]
NoteSort = Literal["newest", "custom"]


class TagResponse(BaseModel):
    id: str
    name: str
    slug: str


class FolderResponse(BaseModel):
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


class NoteAssetResponse(BaseModel):
    id: str
    role: str
    media_type: ContentMediaType
    filename: str
    mime_type: str | None
    size_bytes: int


class NoteCardResponse(BaseModel):
    id: str
    slug: str
    kind: ContentKind
    media_type: ContentMediaType | None
    title: str
    source_filename: str | None
    folder: FolderResponse | None
    tags: list[TagResponse]
    is_favorite: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime
    download_url: str
    collection: CollectionParentResponse | None = None
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


class FavoriteNoteRequest(BaseModel):
    is_favorite: bool


class ReorderNoteItem(BaseModel):
    slug: str
    position: int


class ReorderNotesRequest(BaseModel):
    items: list[ReorderNoteItem] = Field(min_length=1)


class MergeNotesRequest(BaseModel):
    target_slug: str
    source_slugs: list[str] = Field(min_length=1)
    title: str | None = Field(default=None, max_length=512)


class FolderDetailResponse(BaseModel):
    folder: FolderResponse
    tags: list[TagResponse]
    notes: list[NoteCardResponse]
