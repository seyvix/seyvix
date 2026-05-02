from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.contracts.events import (
    ContentObjectChangedPayload,
    EventEnvelope,
    SnapshotRequestedPayload,
)
from app.core.database import Base, build_session_factory
from app.modules.auth.models import User
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.snapshots.infrastructure.repositories import (
    SnapshotJobRepository,
    SnapshotSettingsRepository,
)
from app.modules.snapshots.models import SnapshotJob, SnapshotUserSettings
from app.modules.tags.models import TaggingJob
from app.modules.tags.worker import TagsEventConsumer
from app.modules.taxonomy.models import TaxonomyClassificationJob
from app.modules.taxonomy.worker import TaxonomyEventConsumer
from app.modules.vectorization.models import VectorizationJob
from app.modules.vectorization.worker import VectorizationEventConsumer
from app.platform.events.idempotency import EventAlreadyProcessedError, ProcessedEventStore
from app.platform.events.outbox import EventOutboxRepository
from app.platform.storage.service import LocalVolumeStorage, StorageKeyBuilder


async def _prepare_database(database_url: str) -> async_sessionmaker:
    engine: AsyncEngine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    return build_session_factory(database_url)


def _test_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable database for DB-resetting tests.")
    return database_url


def test_worker_entrypoint_loads_models_needed_by_foreign_keys() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.workers import main; "
                "from app.core.database import Base; "
                "assert {'users', 'content_objects', 'snapshot_jobs'} <= set(Base.metadata.tables)"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_event_envelope_builds_versioned_traceable_content_event() -> None:
    payload = ContentObjectChangedPayload(
        content_object_id="content-1",
        asset_ids=["asset-1"],
        storage_refs=["s3://app-storage/content-assets/content-1/asset-1/original.txt"],
        metadata={"source": "api"},
    )

    envelope = EventEnvelope.new(
        event_name="content.object.created",
        entity_id="content-1",
        correlation_id="correlation-1",
        user_id="user-1",
        payload=payload,
    )

    assert envelope.event_version == 1
    assert envelope.event_name == "content.object.created"
    assert envelope.entity_id == "content-1"
    assert envelope.correlation_id == "correlation-1"
    assert envelope.user_id == "user-1"
    assert envelope.payload["content_object_id"] == "content-1"


def test_event_payload_rejects_large_inline_data_fields() -> None:
    with pytest.raises(ValueError, match="large data"):
        SnapshotRequestedPayload(
            content_object_id="content-1",
            source_asset_id="asset-1",
            job_types=["markdown"],
            metadata={"markdown": "# inline body is not allowed"},
        )


def test_storage_key_builder_uses_predictable_object_keys() -> None:
    assert (
        StorageKeyBuilder.content_asset_original(
            content_object_id="content-1",
            asset_id="asset-1",
            filename="Report Final.pdf",
        )
        == "content-assets/content-1/asset-1/original.pdf"
    )
    assert (
        StorageKeyBuilder.snapshot_artifact(
            content_object_id="content-1",
            snapshot_id="snapshot-1",
            filename="artifact.json",
        )
        == "snapshots/content-1/snapshot-1/artifact.json"
    )


def test_storage_key_builder_preserves_extension_for_non_ascii_filenames() -> None:
    assert (
        StorageKeyBuilder.content_asset_original(
            content_object_id="content-1",
            asset_id="asset-1",
            filename="дневничок.pdf",
        )
        == "content-assets/content-1/asset-1/original.pdf"
    )


def test_local_storage_backend_returns_s3_style_storage_reference(tmp_path: Path) -> None:
    storage = LocalVolumeStorage(root=tmp_path, bucket="app-storage")

    stored = storage.put_bytes(
        storage_key="content-assets/content-1/asset-1/original.txt",
        data=b"hello",
        content_type="text/plain",
    )

    assert stored.storage_backend == "local"
    assert stored.bucket == "app-storage"
    assert stored.storage_key == "content-assets/content-1/asset-1/original.txt"
    assert stored.storage_ref == "s3://app-storage/content-assets/content-1/asset-1/original.txt"
    assert stored.size_bytes == 5
    assert stored.checksum.startswith("sha256:")
    assert storage.get_bytes(stored.storage_key) == b"hello"


def test_outbox_and_processed_events_are_idempotent() -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        async with session_factory() as session:
            outbox = EventOutboxRepository(session)
            event = EventEnvelope.new(
                event_name="content.object.created",
                entity_id="content-1",
                correlation_id="correlation-1",
                user_id="user-1",
                payload=ContentObjectChangedPayload(
                    content_object_id="content-1",
                    asset_ids=[],
                    storage_refs=[],
                ),
            )
            outbox_event = outbox.add(event, routing_key="content.object.created")
            await session.commit()

            pending = await outbox.list_pending(limit=10)
            assert [item.id for item in pending] == [outbox_event.id]

            store = ProcessedEventStore(session)
            await store.mark_processing(
                event_id=event.event_id,
                consumer_name="snapshot-worker",
            )
            with pytest.raises(EventAlreadyProcessedError):
                await store.mark_processing(
                    event_id=event.event_id,
                    consumer_name="snapshot-worker",
                )
            await session.commit()

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for event pipeline tests: {exc}")


def test_snapshot_settings_and_jobs_are_idempotent() -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        async with session_factory() as session:
            owner_user_id = str(uuid4())
            content_object_id = str(uuid4())
            asset_id = str(uuid4())
            user = User(id=owner_user_id, telegram_id="100500", display_name="User")
            content_object = ContentObject(
                id=content_object_id,
                owner_user_id=owner_user_id,
                slug="note",
                title="Note",
                kind="simple",
                media_type="text",
                storage_path="content-assets/object-1",
            )
            asset = ContentAsset(
                id=asset_id,
                content_object=content_object,
                role="original",
                media_type="text",
                filename="note.txt",
                mime_type="text/plain",
                size_bytes=4,
                storage_path="content-assets/object-1/asset-1/original.txt",
            )
            session.add_all([user, content_object, asset])
            await session.commit()

        async def get_settings_once() -> None:
            async with session_factory() as session:
                await SnapshotSettingsRepository(session).get_or_create(owner_user_id)
                await session.commit()

        async def enqueue_once() -> None:
            async with session_factory() as session:
                await SnapshotJobRepository(session).add_once(
                    owner_user_id=owner_user_id,
                    content_object_id=content_object_id,
                    source_asset_id=asset_id,
                    job_type="thumbnail",
                    status="pending",
                    correlation_id="correlation-1",
                    source_event_id="event-1",
                )
                await session.commit()

        await asyncio.gather(get_settings_once(), get_settings_once())
        await asyncio.gather(enqueue_once(), enqueue_once())

        async with session_factory() as session:
            settings = list(await session.scalars(select(SnapshotUserSettings)))
            jobs = list(await session.scalars(select(SnapshotJob)))

        assert len(settings) == 1
        assert len(jobs) == 1

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for event pipeline tests: {exc}")


def test_failed_snapshot_job_is_requeued_instead_of_getting_stuck() -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        owner_user_id = str(uuid4())
        content_object_id = str(uuid4())
        asset_id = str(uuid4())

        async with session_factory() as session:
            user = User(id=owner_user_id, telegram_id="100500", display_name="User")
            content_object = ContentObject(
                id=content_object_id,
                owner_user_id=owner_user_id,
                slug="note",
                title="Note",
                kind="simple",
                media_type="text",
                storage_path="content-assets/object-1",
            )
            asset = ContentAsset(
                id=asset_id,
                content_object=content_object,
                role="original",
                media_type="text",
                filename="note.txt",
                mime_type="text/plain",
                size_bytes=4,
                storage_path="content-assets/object-1/asset-1/original.txt",
            )
            session.add_all([user, content_object, asset])
            await session.commit()

        async with session_factory() as session:
            jobs = SnapshotJobRepository(session)
            await jobs.add_once(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                source_asset_id=asset_id,
                job_type="thumbnail",
                status="pending",
                correlation_id="correlation-1",
                source_event_id="event-1",
            )
            await session.commit()

        async with session_factory() as session:
            job = (await session.scalars(select(SnapshotJob))).one()
            job.status = "failed"
            job.attempts = 1
            job.error_message = "temporary storage failure"
            job.last_error = "temporary storage failure"
            await session.commit()

        async with session_factory() as session:
            await SnapshotJobRepository(session).add_once(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                source_asset_id=asset_id,
                job_type="thumbnail",
                status="pending",
                correlation_id="correlation-2",
                source_event_id="event-2",
            )
            await session.commit()

        async with session_factory() as session:
            jobs = list(await session.scalars(select(SnapshotJob)))

        assert len(jobs) == 1
        assert jobs[0].status == "pending"
        assert jobs[0].attempts == 0
        assert jobs[0].error_message is None
        assert jobs[0].source_event_id == "event-2"

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for event pipeline tests: {exc}")


def test_content_event_creates_module_jobs_idempotently() -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        owner_user_id = str(uuid4())
        content_object_id = str(uuid4())

        async with session_factory() as session:
            user = User(id=owner_user_id, telegram_id="100500", display_name="User")
            content_object = ContentObject(
                id=content_object_id,
                owner_user_id=owner_user_id,
                slug="event-pipeline",
                title="Event pipeline",
                kind="simple",
                media_type="text",
                storage_path=f"content-assets/{content_object_id}",
            )
            session.add_all([user, content_object])
            await session.commit()

        envelope = EventEnvelope.new(
            event_name="content.object.created",
            entity_id=content_object_id,
            correlation_id="correlation-1",
            user_id=owner_user_id,
            payload=ContentObjectChangedPayload(
                content_object_id=content_object_id,
                asset_ids=[],
                storage_refs=[],
            ),
        )

        async with session_factory() as session:
            assert await VectorizationEventConsumer(session).handle_event(envelope) == 1
            assert await TaxonomyEventConsumer(session).handle_event(envelope) == 1
            assert await TagsEventConsumer(session).handle_event(envelope) == 1
            await session.commit()

        async with session_factory() as session:
            assert await VectorizationEventConsumer(session).handle_event(envelope) == 0
            assert await TaxonomyEventConsumer(session).handle_event(envelope) == 0
            assert await TagsEventConsumer(session).handle_event(envelope) == 0
            await session.commit()

        async with session_factory() as session:
            vector_jobs = list(await session.scalars(select(VectorizationJob)))
            taxonomy_jobs = list(await session.scalars(select(TaxonomyClassificationJob)))
            tagging_jobs = list(await session.scalars(select(TaggingJob)))

        assert len(vector_jobs) == 1
        assert vector_jobs[0].source == "content"
        assert vector_jobs[0].source_type == "content_object"
        assert vector_jobs[0].source_id == content_object_id
        assert vector_jobs[0].status == "pending"

        assert len(taxonomy_jobs) == 1
        assert taxonomy_jobs[0].content_object_id == content_object_id
        assert taxonomy_jobs[0].status == "pending"
        assert taxonomy_jobs[0].source_event_id == envelope.event_id

        assert len(tagging_jobs) == 1
        assert tagging_jobs[0].content_object_id == content_object_id
        assert tagging_jobs[0].job_type == "suggest_content_tags"
        assert tagging_jobs[0].status == "pending"

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for event pipeline tests: {exc}")


def test_taxonomy_completion_event_does_not_create_tag_suggestion_job() -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        owner_user_id = str(uuid4())
        content_object_id = str(uuid4())

        async with session_factory() as session:
            user = User(id=owner_user_id, telegram_id="100500", display_name="User")
            content_object = ContentObject(
                id=content_object_id,
                owner_user_id=owner_user_id,
                slug="tag-review",
                title="Tag review",
                kind="simple",
                media_type="text",
                storage_path=f"content-assets/{content_object_id}",
            )
            session.add_all([user, content_object])
            await session.commit()

        envelope = EventEnvelope.new(
            event_name="taxonomy.classification.completed",
            entity_id=content_object_id,
            correlation_id="correlation-1",
            user_id=owner_user_id,
            payload={
                "content_object_id": content_object_id,
                "assignment_id": None,
                "status": "no_assignment",
                "assigned_by": None,
                "confidence": None,
            },
        )

        async with session_factory() as session:
            assert await TagsEventConsumer(session).handle_event(envelope) == 0
            await session.commit()

        async with session_factory() as session:
            assert await TagsEventConsumer(session).handle_event(envelope) == 0
            await session.commit()

        async with session_factory() as session:
            jobs = list(await session.scalars(select(TaggingJob)))

        assert jobs == []

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for event pipeline tests: {exc}")
