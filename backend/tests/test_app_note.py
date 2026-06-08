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


def test_collection_composite_item_exposes_every_child_asset_to_app_note() -> None:
    created_at = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    child = NoteCardResponse(
        id="composite-note-id",
        slug="composite-note",
        kind="complex",
        media_type="image",
        title="Composite",
        source_filename=None,
        taxonomy_category=None,
        tags=[],
        is_favorite=False,
        sort_order=0,
        created_at=created_at,
        updated_at=created_at,
        download_url="/api/v1/notes/composite-note/download",
        assets=[
            NoteAssetResponse(
                id="asset-text",
                role="original",
                media_type="text",
                filename="content.md",
                mime_type="text/markdown",
                size_bytes=12,
                text_content="Caption",
                url="/api/v1/notes/composite-note/asset/asset-text",
            ),
            NoteAssetResponse(
                id="asset-image",
                role="original",
                media_type="image",
                filename="image.jpg",
                mime_type="image/jpeg",
                size_bytes=100,
                url="/api/v1/notes/composite-note/asset/asset-image",
                image_width=1280,
                image_height=720,
            ),
            NoteAssetResponse(
                id="asset-video",
                role="original",
                media_type="video",
                filename="clip.mp4",
                mime_type="video/mp4",
                size_bytes=200,
                url="/api/v1/notes/composite-note/asset/asset-video",
                thumbnail_url="/api/v1/notes/composite-note/asset/asset-video/thumbnail",
            ),
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

    assert [obj.id for obj in app_note.objects] == ["asset-text", "asset-image", "asset-video"]
    assert [obj.object_type for obj in app_note.objects] == ["text", "image", "video"]
    assert [obj.slug for obj in app_note.objects] == ["composite-note"] * 3
    assert [obj.noteId for obj in app_note.objects] == ["composite-note-id"] * 3


def test_note_card_to_app_note_can_limit_text_object_content_for_lists() -> None:
    created_at = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    card = NoteCardResponse(
        id="long-note",
        slug="long-note",
        kind="simple",
        media_type="text",
        title="Long note",
        source_filename=None,
        taxonomy_category=None,
        tags=[],
        is_favorite=False,
        sort_order=0,
        created_at=created_at,
        updated_at=created_at,
        download_url="/api/v1/notes/long-note/download",
        assets=[
            NoteAssetResponse(
                id="asset-text",
                role="original",
                media_type="text",
                filename="content.md",
                mime_type="text/markdown",
                size_bytes=4096,
                text_content="Alpha " * 300,
                url="/api/v1/notes/long-note/asset/asset-text",
            ),
        ],
    )

    full_note = note_card_to_app_note(card)
    list_note = note_card_to_app_note(card, text_content_limit=120)

    assert len(full_note.objects[0].content) > 120
    assert list_note.objects[0].content.endswith("...")
    assert len(list_note.objects[0].content) <= 123
