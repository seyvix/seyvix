"""Tags: manual tag operations, event-driven AI tagging jobs, AI-disabled/unavailable paths."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contracts.events import EventEnvelope
from app.core.config import Settings
from app.core.database import Base, build_session_factory
from app.models import import_all_models
from app.modules.auth.models import User
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.llm.client import AIUnavailableError
from app.modules.tags import worker as tags_worker
from app.modules.tags.models import ContentTagAssignment, Tag, TaggingJob
from app.modules.tags.service import TagsService
from app.modules.tags.tagger import TagSuggestionsOutput
from app.modules.tags.text import slugify_label
from app.modules.tags.worker import TagsEventHandler, TagsJobRunner
from app.platform.events.models import Event, EventDelivery
from app.platform.jobs import JOB_PENDING, JOB_PROCESSING, JOB_SUCCEEDED
from app.platform.storage.local import LocalVolumeStorage
from app.worker.context import WorkerContext

import_all_models()


class FakeAI:
    def __init__(self, output: dict[str, Any] | None = None, error: Exception | None = None):
        self.output = output or {"tags": []}
        self.error = error
        self.calls = 0
        self.before_return: Any = None

    async def chat_json(self, messages: list[dict[str, Any]], schema: type[BaseModel], **_: Any):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.before_return is not None:
            await self.before_return()
        return schema.model_validate(self.output)


@pytest.fixture
def session_factory() -> Iterator[async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable database for DB-resetting tests.")

    async def prepare() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(prepare())
    yield build_session_factory(database_url)


def _ctx(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, **settings: Any
) -> WorkerContext:
    return WorkerContext(
        settings=Settings(_env_file=None, **settings),  # type: ignore[call-arg]
        session_factory=factory,
        storage=LocalVolumeStorage(tmp_path),
        worker_id="test-worker",
    )


async def _seed_note(factory: async_sessionmaker[AsyncSession], body: str) -> tuple[str, str]:
    async with factory() as session:
        user = User(telegram_id="100500", display_name="User")
        session.add(user)
        await session.flush()
        note = ContentObject(
            owner_user_id=user.id, slug="note", title="Benchmarks", kind="simple", media_type="text"
        )
        session.add(note)
        await session.flush()
        session.add(
            ContentAsset(
                content_object_id=note.id,
                role="primary",
                media_type="text",
                filename="note.md",
                size_bytes=len(body),
                storage_key=f"objects/{note.id}/note.md",
                text_content=body,
            )
        )
        await session.commit()
        return user.id, note.id


def _text_ready(owner_id: str, note_id: str) -> EventEnvelope:
    return EventEnvelope.new(
        event_name="snapshot.text_representation.completed",
        entity_id=note_id,
        correlation_id="c0ffee00-0000-0000-0000-000000000000",
        user_id=owner_id,
        payload={"content_object_id": note_id},
    )


async def _handle(ctx: WorkerContext, envelope: EventEnvelope) -> None:
    async with ctx.session_factory() as session:
        await TagsEventHandler(session, ctx).handle_event(envelope)
        await session.commit()


def test_slugify_label_transliterates_cyrillic() -> None:
    assert slugify_label("Машинное обучение") == "mashinnoe-obuchenie"
    assert slugify_label("  KV-cache & vLLM ") == "kv-cache-vllm"
    assert slugify_label("!!!") == ""


def test_event_enqueues_one_job_and_flags_rerun_while_processing(session_factory, tmp_path):
    ctx = _ctx(session_factory, tmp_path, ai_api_key="test-key")

    async def scenario() -> None:
        owner_id, note_id = await _seed_note(session_factory, "vLLM KV-cache latency.")
        await _handle(ctx, _text_ready(owner_id, note_id))
        await _handle(ctx, _text_ready(owner_id, note_id))
        async with session_factory() as session:
            jobs = list(await session.scalars(select(TaggingJob)))
            assert len(jobs) == 1 and jobs[0].status == JOB_PENDING
            jobs[0].status = JOB_PROCESSING
            await session.commit()
        await _handle(ctx, _text_ready(owner_id, note_id))
        async with session_factory() as session:
            job = (await session.scalars(select(TaggingJob))).one()
            assert job.status == JOB_PROCESSING and job.rerun_requested is True

    asyncio.run(scenario())


def test_job_applies_suggestions_touches_note_and_publishes_event(
    session_factory, tmp_path, monkeypatch
):
    ctx = _ctx(session_factory, tmp_path, ai_api_key="test-key")
    fake = FakeAI(
        {
            "tags": [
                {"name": "vLLM", "confidence": 0.95, "reasoning": "main topic"},
                {"name": "Latency", "confidence": 0.7, "reasoning": None},
                {"name": "Misc", "confidence": 0.2, "reasoning": None},
                {"name": "PDF", "confidence": 0.9, "reasoning": "format only"},
            ]
        }
    )
    monkeypatch.setattr(tags_worker, "get_ai_client", lambda _settings: fake)

    async def scenario() -> None:
        owner_id, note_id = await _seed_note(session_factory, "vLLM benchmark: KV-cache latency.")
        async with session_factory() as session:
            before = await session.scalar(
                select(ContentObject.changed_at).where(ContentObject.id == note_id)
            )
        await _handle(ctx, _text_ready(owner_id, note_id))
        assert await TagsJobRunner(ctx).run_once() == 1
        async with session_factory() as session:
            job = (await session.scalars(select(TaggingJob))).one()
            assert job.status == JOB_SUCCEEDED
            rows = (
                await session.execute(
                    select(Tag.slug, ContentTagAssignment.status).join(
                        ContentTagAssignment, ContentTagAssignment.tag_id == Tag.id
                    )
                )
            ).all()
            assert sorted(rows) == [("latency", "suggested"), ("vllm", "accepted")]
            event = (
                await session.scalars(select(Event).where(Event.name == "content.tags.completed"))
            ).one()
            assert event.payload["status"] == JOB_SUCCEEDED
            consumers = set(
                await session.scalars(
                    select(EventDelivery.consumer).where(EventDelivery.event_id == event.id)
                )
            )
            assert consumers == {"taxonomy"}
            after = await session.scalar(
                select(ContentObject.changed_at).where(ContentObject.id == note_id)
            )
            assert after > before

    asyncio.run(scenario())


def test_ai_disabled_skips_tagging_but_lets_taxonomy_run(session_factory, tmp_path):
    ctx = _ctx(session_factory, tmp_path, ai_api_key=None)

    async def scenario() -> None:
        owner_id, note_id = await _seed_note(session_factory, "Some text.")
        await _handle(ctx, _text_ready(owner_id, note_id))
        async with session_factory() as session:
            assert list(await session.scalars(select(TaggingJob))) == []
            event = (await session.scalars(select(Event))).one()
            assert event.name == "content.tags.completed"
            assert event.payload["status"] == "skipped"

    asyncio.run(scenario())


def test_ai_unavailable_retries_with_backoff_without_event(session_factory, tmp_path, monkeypatch):
    ctx = _ctx(session_factory, tmp_path, ai_api_key="test-key")
    fake = FakeAI(error=AIUnavailableError("provider down"))
    monkeypatch.setattr(tags_worker, "get_ai_client", lambda _settings: fake)

    async def scenario() -> None:
        owner_id, note_id = await _seed_note(session_factory, "Text.")
        await _handle(ctx, _text_ready(owner_id, note_id))
        await TagsJobRunner(ctx).run_once()
        async with session_factory() as session:
            job = (await session.scalars(select(TaggingJob))).one()
            assert job.status == JOB_PENDING and job.attempts == 1
            assert job.run_after > datetime.now(UTC) + timedelta(seconds=5)
            assert "provider down" in (job.last_error or "")
            assert list(await session.scalars(select(Event))) == []

    asyncio.run(scenario())


def test_result_is_discarded_and_job_requeued_when_note_changes_meanwhile(
    session_factory, tmp_path, monkeypatch
):
    ctx = _ctx(session_factory, tmp_path, ai_api_key="test-key")
    fake = FakeAI({"tags": [{"name": "Old topic", "confidence": 0.99, "reasoning": None}]})
    monkeypatch.setattr(tags_worker, "get_ai_client", lambda _settings: fake)

    async def scenario() -> None:
        owner_id, note_id = await _seed_note(session_factory, "Old text.")

        async def edit_note() -> None:
            async with session_factory() as session:
                await session.execute(
                    update(ContentObject)
                    .where(ContentObject.id == note_id)
                    .values(updated_at=datetime.now(UTC) + timedelta(seconds=1))
                )
                await session.commit()

        fake.before_return = edit_note
        await _handle(ctx, _text_ready(owner_id, note_id))
        await TagsJobRunner(ctx).run_once()
        async with session_factory() as session:
            job = (await session.scalars(select(TaggingJob))).one()
            assert job.status == JOB_PENDING and job.attempts == 0
            assert list(await session.scalars(select(ContentTagAssignment))) == []

    asyncio.run(scenario())


def test_rejected_tag_is_not_suggested_again(session_factory, tmp_path, monkeypatch):
    ctx = _ctx(session_factory, tmp_path, ai_api_key="test-key")
    fake = FakeAI({"tags": [{"name": "Latency", "confidence": 0.7, "reasoning": None}]})
    monkeypatch.setattr(tags_worker, "get_ai_client", lambda _settings: fake)

    async def scenario() -> None:
        owner_id, note_id = await _seed_note(session_factory, "Latency notes.")
        await _handle(ctx, _text_ready(owner_id, note_id))
        await TagsJobRunner(ctx).run_once()
        async with session_factory() as session:
            assignment = (await session.scalars(select(ContentTagAssignment))).one()
            await TagsService(session).reject_suggestion(
                owner_user_id=owner_id,
                content_object_id=note_id,
                assignment_id=assignment.id,
                assigned_by_user_id=owner_id,
            )
        await _handle(ctx, _text_ready(owner_id, note_id))
        await TagsJobRunner(ctx).run_once()
        async with session_factory() as session:
            statuses = list(await session.scalars(select(ContentTagAssignment.status)))
            assert statuses == ["rejected"]

    asyncio.run(scenario())


def test_manual_tags_replace_merge_and_aliases(session_factory, tmp_path):
    async def scenario() -> None:
        owner_id, note_id = await _seed_note(session_factory, "Text.")
        async with session_factory() as session:
            service = TagsService(session)
            await service.replace_manual_tags_for_content(
                owner_user_id=owner_id,
                content_object_id=note_id,
                tag_names=["Машинное обучение", "ML", "ml"],
                assigned_by_user_id=owner_id,
            )
            await session.commit()
            tags = await service.list_active_tags_for_contents(
                owner_user_id=owner_id, content_object_ids=[note_id]
            )
            by_slug = {tag.slug: tag for tag in tags[note_id]}
            assert set(by_slug) == {"mashinnoe-obuchenie", "ml"}

            merged = await service.merge_tags(
                owner_user_id=owner_id,
                source_tag_id=by_slug["ml"].id,
                target_tag_id=by_slug["mashinnoe-obuchenie"].id,
            )
            assert "ml" in merged.aliases
            tags = await service.list_active_tags_for_contents(
                owner_user_id=owner_id, content_object_ids=[note_id]
            )
            assert [tag.slug for tag in tags[note_id]] == ["mashinnoe-obuchenie"]
            # Typing the merged name again resolves to the target through its alias.
            await service.replace_manual_tags_for_content(
                owner_user_id=owner_id,
                content_object_id=note_id,
                tag_names=["ML"],
                assigned_by_user_id=owner_id,
            )
            await session.commit()
            tags = await service.list_active_tags_for_contents(
                owner_user_id=owner_id, content_object_ids=[note_id]
            )
            assert [tag.slug for tag in tags[note_id]] == ["mashinnoe-obuchenie"]

    asyncio.run(scenario())


def test_tagger_output_schema_accepts_empty_result() -> None:
    assert TagSuggestionsOutput.model_validate({"tags": []}).tags == []
