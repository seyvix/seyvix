from __future__ import annotations

from pydantic import BaseModel


class SnapshotFormatSettings(BaseModel):
    screenshot: bool
    webpage_html: bool
    pdf: bool
    markdown: bool
    archive_org: bool


class SnapshotFormatOverrides(BaseModel):
    screenshot: bool | None = None
    webpage_html: bool | None = None
    pdf: bool | None = None
    markdown: bool | None = None
    archive_org: bool | None = None


class SnapshotSettingsResponse(BaseModel):
    effective: SnapshotFormatSettings
    overrides: SnapshotFormatOverrides


class UpdateSnapshotSettingsRequest(BaseModel):
    screenshot: bool | None = None
    webpage_html: bool | None = None
    pdf: bool | None = None
    markdown: bool | None = None
    archive_org: bool | None = None


class SnapshotJobResponse(BaseModel):
    id: str
    content_object_id: str
    source_asset_id: str | None
    job_type: str
    status: str
    attempts: int
    error_message: str | None


class SnapshotJobListResponse(BaseModel):
    items: list[SnapshotJobResponse]


class SnapshotArtifactResponse(BaseModel):
    id: str
    content_object_id: str
    source_asset_id: str | None
    artifact_type: str
    filename: str
    mime_type: str
    size_bytes: int
    status: str
    url: str


class SnapshotArtifactListResponse(BaseModel):
    items: list[SnapshotArtifactResponse]
