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
    ContentTagsCompletedPayload,
    EventEnvelope,
    SnapshotRequestedPayload,
    SnapshotTextRepresentationCompletedPayload,
)
from app.core.config import get_settings
from app.core.database import Base, build_session_factory
from app.modules.auth.models import User
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.content.service import ContentService
from app.modules.snapshots.infrastructure.repositories import (
    SnapshotJobRepository,
    SnapshotSettingsRepository,
)
from app.modules.snapshots.models import SnapshotArtifact, SnapshotJob, SnapshotUserSettings
from app.modules.snapshots.service import SnapshotService
from app.modules.snapshots.worker import SnapshotWorker
from app.modules.tags.models import TaggingJob
from app.modules.tags.worker import TagsEventConsumer
from app.modules.taxonomy.models import TaxonomyClassificationJob
from app.modules.taxonomy.worker import TaxonomyEventConsumer
from app.modules.vectorization.models import VectorizationJob
from app.modules.vectorization.worker import VectorizationEventConsumer
from app.platform.events import topology
from app.platform.events.idempotency import EventAlreadyProcessedError, ProcessedEventStore
from app.platform.events.models import EventOutbox
from app.platform.events.outbox import EventOutboxRepository
from app.platform.storage.models import StorageObject
from app.platform.storage.repositories import StorageObjectRepository
from app.platform.storage.service import (
    LocalVolumeStorage,
    S3CompatibleStorage,
    StorageKeyBuilder,
    StoredObject,
)


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


def test_rabbit_connection_retry_waits_for_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    delays: list[float] = []
    connection = object()

    async def connect_robust(rabbitmq_url: str) -> object:
        nonlocal attempts
        assert rabbitmq_url == "amqp://guest:guest@rabbitmq:5672/"
        attempts += 1
        if attempts == 1:
            raise OSError("broker is still booting")
        return connection

    async def sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(topology.aio_pika, "connect_robust", connect_robust)
    monkeypatch.setattr(topology.asyncio, "sleep", sleep)

    result = asyncio.run(
        topology._connect_rabbit_with_retry(
            "amqp://guest:guest@rabbitmq:5672/",
            max_attempts=2,
            retry_delay_seconds=0.01,
        )
    )

    assert result is connection
    assert attempts == 2
    assert delays == [0.01]


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


def test_content_and_snapshot_services_default_to_configured_storage_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://minio:9000")
    get_settings.cache_clear()
    try:
        session = object()
        content_service = ContentService(session)  # type: ignore[arg-type]
        snapshot_service = SnapshotService(session)  # type: ignore[arg-type]

        assert isinstance(content_service.storage.backend, S3CompatibleStorage)
        assert isinstance(content_service.snapshots.storage_backend, S3CompatibleStorage)
        assert isinstance(snapshot_service.storage_backend, S3CompatibleStorage)
    finally:
        get_settings.cache_clear()


def test_storage_object_repository_upserts_existing_storage_key() -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        async with session_factory() as session:
            repository = StorageObjectRepository(session)
            await repository.upsert(
                StoredObject(
                    storage_backend="local",
                    bucket="app-storage",
                    storage_key="snapshots/content-1/job-1/snapshot.md",
                    storage_ref="s3://app-storage/snapshots/content-1/job-1/snapshot.md",
                    content_type="text/markdown",
                    size_bytes=5,
                    checksum="sha256:first",
                ),
                owner_entity_type="snapshot_artifact",
                owner_entity_id="artifact-1",
                metadata={"job_type": "markdown"},
            )
            await repository.upsert(
                StoredObject(
                    storage_backend="local",
                    bucket="app-storage",
                    storage_key="snapshots/content-1/job-1/snapshot.md",
                    storage_ref="s3://app-storage/snapshots/content-1/job-1/snapshot.md",
                    content_type="text/markdown",
                    size_bytes=12,
                    checksum="sha256:second",
                ),
                owner_entity_type="snapshot_artifact",
                owner_entity_id="artifact-1",
                metadata={"job_type": "markdown", "extraction": {"method": "pdf"}},
            )
            await session.commit()

            rows = list(await session.scalars(select(StorageObject)))

        assert len(rows) == 1
        assert rows[0].size_bytes == 12
        assert rows[0].checksum == "sha256:second"
        assert rows[0].metadata_["extraction"] == {"method": "pdf"}

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for storage repository tests: {exc}")


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


def test_content_event_no_longer_creates_downstream_jobs_before_text_is_ready() -> None:
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
            assert await VectorizationEventConsumer(session).handle_event(envelope) == 0
            assert await TaxonomyEventConsumer(session).handle_event(envelope) == 0
            assert await TagsEventConsumer(session).handle_event(envelope) == 0
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

        assert vector_jobs == []
        assert taxonomy_jobs == []
        assert tagging_jobs == []

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for event pipeline tests: {exc}")


def test_text_representation_and_tag_completion_events_create_downstream_jobs_idempotently() -> (
    None
):
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        owner_user_id = str(uuid4())
        content_object_id = str(uuid4())
        asset_id = str(uuid4())
        artifact_id = str(uuid4())

        async with session_factory() as session:
            user = User(id=owner_user_id, telegram_id="100500", display_name="User")
            content_object = ContentObject(
                id=content_object_id,
                owner_user_id=owner_user_id,
                slug="text-ready",
                title="Text ready",
                kind="simple",
                media_type="image",
                storage_path=f"content-assets/{content_object_id}",
            )
            asset = ContentAsset(
                id=asset_id,
                content_object=content_object,
                role="original",
                media_type="image",
                filename="diagram.png",
                mime_type="image/png",
                size_bytes=120,
                storage_path=f"content-assets/{content_object_id}/{asset_id}/original.png",
            )
            session.add_all([user, content_object, asset])
            await session.commit()

        content_event = EventEnvelope.new(
            event_name="content.object.created",
            entity_id=content_object_id,
            correlation_id="correlation-1",
            user_id=owner_user_id,
            payload=ContentObjectChangedPayload(
                content_object_id=content_object_id,
                asset_ids=[asset_id],
                storage_refs=[],
            ),
        )
        text_event = EventEnvelope.new(
            event_name="snapshot.text_representation.completed",
            entity_id=content_object_id,
            correlation_id="correlation-1",
            user_id=owner_user_id,
            payload=SnapshotTextRepresentationCompletedPayload(
                content_object_id=content_object_id,
                source_asset_id=asset_id,
                artifact_id=artifact_id,
                representation_type="markdown",
                source_media_type="image",
                source_mime_type="image/png",
                source_filename="diagram.png",
                metadata={"job_type": "markdown"},
            ),
        )

        async with session_factory() as session:
            assert await VectorizationEventConsumer(session).handle_event(content_event) == 0
            assert await TaxonomyEventConsumer(session).handle_event(content_event) == 0
            assert await TagsEventConsumer(session).handle_event(content_event) == 0
            await session.commit()

        async with session_factory() as session:
            assert await VectorizationEventConsumer(session).handle_event(text_event) == 1
            assert await TaxonomyEventConsumer(session).handle_event(text_event) == 0
            assert await TagsEventConsumer(session).handle_event(text_event) == 1
            await session.commit()

        async with session_factory() as session:
            vector_jobs = list(await session.scalars(select(VectorizationJob)))
            taxonomy_jobs = list(await session.scalars(select(TaxonomyClassificationJob)))
            tagging_jobs = list(await session.scalars(select(TaggingJob)))

        assert len(vector_jobs) == 1
        assert vector_jobs[0].source_id == content_object_id
        assert vector_jobs[0].status == "pending"

        assert len(tagging_jobs) == 1
        assert tagging_jobs[0].content_object_id == content_object_id
        assert tagging_jobs[0].source_event_id == text_event.event_id
        assert tagging_jobs[0].correlation_id == text_event.correlation_id

        assert taxonomy_jobs == []

        tags_completed_event = EventEnvelope.new(
            event_name="content.tags.completed",
            entity_id=content_object_id,
            correlation_id=text_event.correlation_id,
            user_id=owner_user_id,
            payload=ContentTagsCompletedPayload(
                content_object_id=content_object_id,
                tagging_job_id=tagging_jobs[0].id,
                job_type=tagging_jobs[0].job_type,
                status="succeeded",
            ),
        )

        async with session_factory() as session:
            assert await VectorizationEventConsumer(session).handle_event(text_event) == 0
            assert await TagsEventConsumer(session).handle_event(text_event) == 0
            assert await TaxonomyEventConsumer(session).handle_event(tags_completed_event) == 1
            await session.commit()

        async with session_factory() as session:
            taxonomy_jobs = list(await session.scalars(select(TaxonomyClassificationJob)))

        assert len(taxonomy_jobs) == 1
        assert taxonomy_jobs[0].content_object_id == content_object_id
        assert taxonomy_jobs[0].source_event_id == tags_completed_event.event_id

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for event pipeline tests: {exc}")


def test_markdown_snapshot_job_publishes_text_representation_event(tmp_path: Path) -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        owner_user_id = str(uuid4())
        content_object_id = str(uuid4())
        asset_id = str(uuid4())
        storage_root = tmp_path / "content-storage"
        storage_backend = LocalVolumeStorage(root=storage_root, bucket="app-storage")
        stored = storage_backend.put_bytes(
            storage_key=f"content-assets/{content_object_id}/{asset_id}/original.txt",
            data=b"Extracted text must trigger downstream processing.",
            content_type="text/plain",
        )

        async with session_factory() as session:
            user = User(id=owner_user_id, telegram_id="100500", display_name="User")
            content_object = ContentObject(
                id=content_object_id,
                owner_user_id=owner_user_id,
                slug="snapshot-text",
                title="Snapshot text",
                kind="simple",
                media_type="text",
                storage_path=f"content-assets/{content_object_id}",
            )
            asset = ContentAsset(
                id=asset_id,
                content_object=content_object,
                role="original",
                media_type="text",
                filename="note.txt",
                mime_type="text/plain",
                size_bytes=stored.size_bytes,
                storage_path=stored.storage_key,
                storage_backend=stored.storage_backend,
                bucket=stored.bucket,
                storage_key=stored.storage_key,
                storage_ref=stored.storage_ref,
                checksum=stored.checksum,
            )
            job = SnapshotJob(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                source_asset_id=asset_id,
                job_type="markdown",
                status="pending",
                correlation_id="correlation-1",
                source_event_id="event-1",
            )
            session.add_all([user, content_object, asset])
            await session.flush()
            session.add(job)
            await session.commit()

        async with session_factory() as session:
            processed = await SnapshotWorker(
                session,
                storage_root,
                storage_backend,
            ).run_once(limit=1)
            assert processed == 1

        async with session_factory() as session:
            artifacts = list(await session.scalars(select(SnapshotArtifact)))
            events = list(await session.scalars(select(EventOutbox)))

        assert [artifact.artifact_type for artifact in artifacts] == ["markdown"]
        assert [event.event_name for event in events] == ["snapshot.text_representation.completed"]
        assert events[0].entity_id == content_object_id
        assert events[0].payload["source_asset_id"] == asset_id
        assert events[0].payload["artifact_id"] == artifacts[0].id

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for event pipeline tests: {exc}")


def test_content_service_only_enqueues_snapshot_jobs_directly(tmp_path: Path) -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        async with session_factory() as session:
            user = User(telegram_id="100510", display_name="User")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            await ContentService(session, tmp_path / "content-storage").create_note(
                owner_user_id=user.id,
                media_type="text",
                text="Event-driven jobs are created by Rabbit consumers.",
                title="Event-driven note",
                folder_path=None,
                tag_names=[],
                file_upload_ids=[],
            )

            taxonomy_jobs = list(await session.scalars(select(TaxonomyClassificationJob)))
            tagging_jobs = list(await session.scalars(select(TaggingJob)))

        assert taxonomy_jobs == []
        assert tagging_jobs == []

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
