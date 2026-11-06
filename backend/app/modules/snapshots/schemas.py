from __future__ import annotations

from pydantic import BaseModel

from app.modules.snapshots.planning import SnapshotJobType


class SnapshotFormatOption(BaseModel):
    key: str
    label: str
    description: str
    server_enabled: bool


class SnapshotFormatSettings(BaseModel):
    screenshot: bool
    webpage_html: bool
    pdf: bool
    markdown: bool


class SnapshotFormatOverrides(BaseModel):
    screenshot: bool | None = None
    webpage_html: bool | None = None
    pdf: bool | None = None
    markdown: bool | None = None


class SnapshotSettingsResponse(BaseModel):
    available: list[SnapshotFormatOption]
    effective: SnapshotFormatSettings
    overrides: SnapshotFormatOverrides


class UpdateSnapshotSettingsRequest(BaseModel):
    screenshot: bool | None = None
    webpage_html: bool | None = None
    pdf: bool | None = None
    markdown: bool | None = None


class SnapshotJobResponse(BaseModel):
    id: str
    content_object_id: str
    source_asset_id: str | None
    job_type: str
    # pending | processing | done | failed | cancelled
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


class ReprocessSnapshotsRequest(BaseModel):
    content_object_id: str | None = None
    source_asset_id: str | None = None
    job_types: list[SnapshotJobType] | None = None
    force: bool = True


class ReprocessSnapshotsResponse(BaseModel):
    queued_count: int
    job_ids: list[str]
    source_asset_ids: list[str]
