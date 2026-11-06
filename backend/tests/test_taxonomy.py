"""Taxonomy: onboarding presets, rule-based classification without AI, LLM judge, user choice."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contracts.events import EventEnvelope
from app.core.config import Settings
from app.core.database import Base, build_session_factory
from app.models import import_all_models
from app.modules.auth.models import User
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.llm.client import AIUnavailableError
from app.modules.taxonomy import worker as taxonomy_worker
from app.modules.taxonomy.models import (
    TaxonomyCategory,
    TaxonomyClassificationJob,
    TaxonomyContentAssignment,
)
from app.modules.taxonomy.onboarding import interest_specs, list_interest_options
from app.modules.taxonomy.service import TaxonomyService
from app.modules.taxonomy.worker import TaxonomyEventHandler, TaxonomyJobRunner
from app.platform.jobs import JOB_PENDING, JOB_SUCCEEDED
from app.platform.storage.local import LocalVolumeStorage
from app.worker.context import WorkerContext

import_all_models()

LLM_NOTE = "ChatGPT prompts for LLM chatbots: structured output and tool calling with Claude."


class FakeAI:
    def __init__(self, judge: dict[str, Any] | None = None, embed_error: Exception | None = None):
        self.judge = judge
        self.embed_error = embed_error

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.embed_error is not None:
            raise self.embed_error
        dimensions = Settings(_env_file=None).ai_embedding_dimensions  # type: ignore[call-arg]
        return [[0.01] * dimensions for _ in texts]

    async def chat_json(self, messages: list[dict[str, Any]], schema: type[BaseModel], **_: Any):
        return schema.model_validate(self.judge)


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


async def _seed(factory: async_sessionmaker[AsyncSession], body: str) -> tuple[str, str]:
    """User with the `ai` interest preset and one text note."""
    async with factory() as session:
        user = User(telegram_id="100501", display_name="User")
        session.add(user)
        await session.flush()
        note = ContentObject(
            owner_user_id=user.id,
            slug="note",
            title="Prompt notes",
            kind="simple",
            media_type="text",
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
        await TaxonomyService(session).initialize_from_interests(
            owner_user_id=user.id, interest_slugs=["ai"], custom_description=None, ai=None
        )
        return user.id, note.id


async def _enqueue(ctx: WorkerContext, owner_id: str, note_id: str) -> None:
    envelope = EventEnvelope.new(
        event_name="content.tags.completed",
        entity_id=note_id,
        correlation_id="c0ffee00-0000-0000-0000-000000000001",
        user_id=owner_id,
        payload={"content_object_id": note_id, "status": "skipped"},
    )
    async with ctx.session_factory() as session:
        await TaxonomyEventHandler(session, ctx).handle_event(envelope)
        await session.commit()


async def _current(factory: async_sessionmaker[AsyncSession]) -> TaxonomyContentAssignment:
    async with factory() as session:
        return (
            await session.scalars(
                select(TaxonomyContentAssignment).where(
                    TaxonomyContentAssignment.is_current.is_(True)
                )
            )
        ).one()


def test_interest_presets_are_valid_and_listed() -> None:
    options = list_interest_options()
    assert {option.slug for option in options} == set(interest_specs())
    assert all(option.name and option.description for option in options)


def test_classifies_without_ai_by_profile_keywords(session_factory, tmp_path):
    ctx = _ctx(session_factory, tmp_path, ai_api_key=None)

    async def scenario() -> None:
        owner_id, note_id = await _seed(session_factory, LLM_NOTE)
        await _enqueue(ctx, owner_id, note_id)
        await _enqueue(ctx, owner_id, note_id)  # duplicate events -> one job
        assert await TaxonomyJobRunner(ctx).run_once() == 1
        async with session_factory() as session:
            job = (await session.scalars(select(TaxonomyClassificationJob))).one()
            assert job.status == JOB_SUCCEEDED and job.assignment_id is not None
        assignment = await _current(session_factory)
        assert assignment.assigned_by == "system"
        assert assignment.category_path_snapshot.startswith("ai/")

    asyncio.run(scenario())


def test_llm_judge_picks_a_candidate(session_factory, tmp_path, monkeypatch):
    ctx = _ctx(session_factory, tmp_path, ai_api_key="test-key")
    fake = FakeAI(
        judge={
            "selected_candidate_id": "c1",
            "confidence": 0.93,
            "should_assign": True,
            "status": "accepted",
            "reasoning": "About LLM chatbots.",
            "alternatives": [{"candidate_id": "c9", "confidence": 0.1, "reasoning": "unknown"}],
        }
    )
    monkeypatch.setattr(taxonomy_worker, "get_ai_client", lambda _settings: fake)

    async def scenario() -> None:
        owner_id, note_id = await _seed(session_factory, LLM_NOTE)
        await _enqueue(ctx, owner_id, note_id)
        await TaxonomyJobRunner(ctx).run_once()
        assignment = await _current(session_factory)
        assert assignment.assigned_by == "llm"
        assert assignment.status == "accepted"
        assert float(assignment.confidence or 0) == pytest.approx(0.93)

    asyncio.run(scenario())


def test_ai_outage_retries_instead_of_degrading_early(session_factory, tmp_path, monkeypatch):
    ctx = _ctx(session_factory, tmp_path, ai_api_key="test-key")
    fake = FakeAI(embed_error=AIUnavailableError("down"))
    monkeypatch.setattr(taxonomy_worker, "get_ai_client", lambda _settings: fake)

    async def scenario() -> None:
        owner_id, note_id = await _seed(session_factory, LLM_NOTE)
        await _enqueue(ctx, owner_id, note_id)
        await TaxonomyJobRunner(ctx).run_once()
        async with session_factory() as session:
            job = (await session.scalars(select(TaxonomyClassificationJob))).one()
            assert job.status == JOB_PENDING and job.attempts == 1
            assert list(await session.scalars(select(TaxonomyContentAssignment))) == []

    asyncio.run(scenario())


def test_automatic_classification_keeps_user_choice(session_factory, tmp_path):
    ctx = _ctx(session_factory, tmp_path, ai_api_key=None)

    async def scenario() -> None:
        owner_id, note_id = await _seed(session_factory, LLM_NOTE)
        async with session_factory() as session:
            await TaxonomyService(session).assign_content_to_path(
                owner_user_id=owner_id,
                content_object_id=note_id,
                raw_path="Personal/Reading",
                reasoning=None,
                commit=True,
            )
        await _enqueue(ctx, owner_id, note_id)
        await TaxonomyJobRunner(ctx).run_once()
        async with session_factory() as session:
            job = (await session.scalars(select(TaxonomyClassificationJob))).one()
            assert job.result_status == "kept_user_choice"
        assignment = await _current(session_factory)
        assert assignment.assigned_by == "user"
        assert assignment.category_path_snapshot == "personal/reading"

    asyncio.run(scenario())


def test_delete_category_moves_notes_to_inbox_and_reclassify_enqueues(session_factory, tmp_path):
    async def scenario() -> None:
        owner_id, note_id = await _seed(session_factory, LLM_NOTE)
        async with session_factory() as session:
            service = TaxonomyService(session)
            await service.assign_content_to_path(
                owner_user_id=owner_id,
                content_object_id=note_id,
                raw_path="projects/alpha",
                reasoning=None,
                commit=True,
            )
            projects = (
                await session.scalars(
                    select(TaxonomyCategory).where(TaxonomyCategory.path == "projects")
                )
            ).one()
            result = await service.delete_category(
                owner_user_id=owner_id,
                category_id=projects.id,
                delete_notes=False,
                confirm_category_name=None,
                confirm_delete_notes_text=None,
                storage=LocalVolumeStorage(tmp_path),
            )
            assert result.archived_categories_count == 2
            assert result.moved_notes_count == 1
            response = await service.enqueue_inbox_reclassification_jobs(owner_user_id=owner_id)
            assert response.enqueued_count == 1
        assignment = await _current(session_factory)
        assert assignment.category_path_snapshot == "inbox"

    asyncio.run(scenario())
