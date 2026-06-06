from __future__ import annotations

from datetime import UTC, datetime

from app.modules.content.app_note import note_card_to_app_note
from app.modules.content.schemas import NoteAssetResponse, NoteCardResponse


def test_collection_video_item_exposes_thumbnail_url_to_app_note() -> None:
    created_at = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    child = NoteCardResponse(
        id="video-note",
        slug="video-note",
        kind="simple",
        media_type="video",
        title="Video",
        source_filename="clip.mp4",
        taxonomy_category=None,
        tags=[],
        is_favorite=False,
        sort_order=0,
        created_at=created_at,
        updated_at=created_at,
        download_url="/api/v1/notes/video-note/download",
        assets=[
            NoteAssetResponse(
                id="asset-1",
                role="original",
                media_type="video",
                filename="clip.mp4",
                mime_type="video/mp4",
                size_bytes=100,
                url="/api/v1/notes/video-note/asset/asset-1",
                thumbnail_url="/api/v1/notes/video-note/asset/asset-1/thumbnail",
            )
        ],
    )
    collection = NoteCardResponse(
        id="collection",
        slug="collection",
        kind="collection",
        media_type=None,
        title="Collection",
        source_filename=None,
        taxonomy_category=None,
        tags=[],
        is_favorite=False,
        sort_order=0,
        created_at=created_at,
        updated_at=created_at,
        download_url="/api/v1/notes/collection/download",
        items=[child],
    )

    app_note = note_card_to_app_note(collection)

    assert app_note.objects[0].object_type == "video"
    assert app_note.objects[0].thumbnailUrl == "/api/v1/notes/video-note/asset/asset-1/thumbnail"
