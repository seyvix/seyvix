import asyncio
import hashlib
import hmac
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.database import Base, build_session_factory
from app.main import app
from app.modules.auth.models import User
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.content.service import ContentService
from app.modules.tags.infrastructure.llm_tagger import LLMContentTagger
from app.modules.tags.models import ContentTagAssignment, Tag, TaggingJob
from app.modules.tags.service import TagsService
from app.modules.tags.worker import TagsWorker
from app.modules.taxonomy.models import ClassificationFeedback

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


class FakeStructuredGenerator:
    def __init__(self, response: dict[str, Any] | None = None, fail: Exception | None = None):
        self.response = response or {"tags": []}
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        model_config: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "schema": schema, "model_config": model_config})
        if self.fail is not None:
            raise self.fail
        return self.response


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


@pytest.fixture
def tags_client(tmp_path: Path) -> Iterator[TestClient]:
    os.environ["TELEGRAM_BOT_TOKEN"] = TELEGRAM_BOT_TOKEN
    os.environ["TAGS_LLM_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        app.state.session_factory = asyncio.run(_prepare_database(_test_database_url()))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for tags tests: {exc}")
    app.state.content_storage_root = tmp_path / "content-storage"
    app.state.storage_backend = None
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def _telegram_payload(telegram_id: int = 100500) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": telegram_id,
        "first_name": "User",
        "auth_date": int(datetime.now(UTC).timestamp()),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode("utf-8")).digest()
    payload["hash"] = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return payload


def _auth_headers(client: TestClient, telegram_id: int = 100500) -> dict[str, str]:
    response = client.post("/api/v1/auth/telegram-login", json=_telegram_payload(telegram_id))
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_note(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str = "Taggable note",
    text: str = "vLLM benchmark notes with KV-cache latency details.",
    tag_names: list[str] | None = None,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "media_type": "text",
            "title": title,
            "text": text,
            "tag_names": tag_names or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_tag_crud_manual_assignment_and_content_response_integration(
    tags_client: TestClient,
) -> None:
    headers = _auth_headers(tags_client)
    note = _create_note(tags_client, headers, tag_names=["legacy compat"])

    list_response = tags_client.get("/api/v1/notes", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["tags"] == note["tags"]
    assert note["tags"][0]["slug"] == "legacy-compat"

    create_response = tags_client.post(
        "/api/v1/tags",
        headers=headers,
        json={"name": "vLLM", "description": "LLM inference server."},
    )
    assert create_response.status_code == 201, create_response.text
    tag = create_response.json()
    assert tag["slug"] == "vllm"
    assert tag["created_by_type"] == "user"
    assert tag["source"] == "manual"

    duplicate_response = tags_client.post(
        "/api/v1/tags",
        headers=headers,
        json={"name": " VLLM "},
    )
    assert duplicate_response.status_code == 409

    assign_response = tags_client.post(
        f"/api/v1/content/{note['id']}/tags",
        headers=headers,
        json={"tag_id": tag["id"], "reasoning": "Manual curation."},
    )
    assert assign_response.status_code == 201, assign_response.text
    assignment = assign_response.json()
    assert assignment["status"] == "accepted"
    assert assignment["assigned_by_type"] == "user"
    assert assignment["source"] == "manual"
    assert assignment["reasoning"] == "Manual curation."

    repeat_response = tags_client.post(
        f"/api/v1/content/{note['id']}/tags",
        headers=headers,
        json={"tag_id": tag["id"]},
    )
    assert repeat_response.status_code == 200
    assert repeat_response.json()["id"] == assignment["id"]

    note_response = tags_client.get(f"/api/v1/notes/{note['slug']}", headers=headers)
    assert note_response.status_code == 200
    assert {item["slug"] for item in note_response.json()["tags"]} == {"legacy-compat", "vllm"}

    remove_response = tags_client.delete(
        f"/api/v1/content/{note['id']}/tags/{tag['id']}",
        headers=headers,
    )
    assert remove_response.status_code == 204
    removed_note_response = tags_client.get(f"/api/v1/notes/{note['slug']}", headers=headers)
    assert {item["slug"] for item in removed_note_response.json()["tags"]} == {"legacy-compat"}

    archive_response = tags_client.delete(f"/api/v1/tags/{tag['id']}", headers=headers)
    assert archive_response.status_code == 204
    archived_assign_response = tags_client.post(
        f"/api/v1/content/{note['id']}/tags",
        headers=headers,
        json={"tag_id": tag["id"]},
    )
    assert archived_assign_response.status_code == 409


def test_content_tag_jobs_endpoint_lists_jobs_for_current_user(tags_client: TestClient) -> None:
    headers = _auth_headers(tags_client)
    note = _create_note(tags_client, headers)

    async def seed_job() -> None:
        async with app.state.session_factory() as session:
            content_object = await session.get(ContentObject, note["id"])
            assert content_object is not None
            session.add(
                TaggingJob(
                    owner_user_id=content_object.owner_user_id,
                    content_object_id=content_object.id,
                    job_type="suggest_content_tags",
                    status="processing",
                    attempts=1,
                    last_error=None,
                ),
            )
            await session.commit()

    tags_client.portal.call(seed_job)

    response = tags_client.get(f"/api/v1/content/{note['id']}/tags/jobs", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"][0]["content_object_id"] == note["id"]
    assert payload["items"][0]["job_type"] == "suggest_content_tags"
    assert payload["items"][0]["status"] == "processing"
    assert payload["items"][0]["attempts"] == 1


def test_tags_enforce_owner_isolation(tags_client: TestClient) -> None:
    first_headers = _auth_headers(tags_client, telegram_id=100501)
    second_headers = _auth_headers(tags_client, telegram_id=100502)
    note = _create_note(tags_client, first_headers)
    tag_response = tags_client.post(
        "/api/v1/tags",
        headers=second_headers,
        json={"name": "PostgreSQL"},
    )
    assert tag_response.status_code == 201

    cross_owner_assign = tags_client.post(
        f"/api/v1/content/{note['id']}/tags",
        headers=second_headers,
        json={"tag_id": tag_response.json()["id"]},
    )
    assert cross_owner_assign.status_code == 404

    first_user_assign_other_tag = tags_client.post(
        f"/api/v1/content/{note['id']}/tags",
        headers=first_headers,
        json={"tag_id": tag_response.json()["id"]},
    )
    assert first_user_assign_other_tag.status_code == 404


def test_llm_dry_run_and_disabled_enqueue_behavior(tags_client: TestClient) -> None:
    headers = _auth_headers(tags_client)
    note = _create_note(tags_client, headers)

    disabled_response = tags_client.post(
        f"/api/v1/content/{note['id']}/tags/suggest",
        headers=headers,
        json={"dry_run": False, "max_tags": 8},
    )
    assert disabled_response.status_code == 409
    assert disabled_response.json()["error"]["code"] == "tags_llm_disabled"


def test_llm_tagger_prompt_requests_grounded_multi_level_tags() -> None:
    tagger = LLMContentTagger(
        settings=Settings(tags_llm_prompt_version="test-tags-v2"),
        llm_generator=FakeStructuredGenerator(),
    )

    prompt = tagger._build_prompt(
        title="pgvector indexing benchmark",
        url=None,
        existing_tags=["PostgreSQL", "vector search"],
        excerpt="PostgreSQL indexing notes. Use pgvector for nearest-neighbor search.",
        metadata={"media_type": "text", "source_filename": "pgvector.md"},
        max_tags=6,
    )

    assert "Title: pgvector indexing benchmark" in prompt
    assert "Metadata:" in prompt
    assert "source_filename" in prompt
    assert "Existing candidate tags: PostgreSQL, vector search" in prompt
    assert "different levels of abstraction" in prompt
    assert "broad categories" in prompt
    assert "specific topics" in prompt
    assert "metadata only to understand context and provenance" in prompt
    assert "do not tag the source" in prompt
    assert "Only suggest tags supported by the provided title, metadata, and text" in prompt
    assert "Good tags: vLLM" not in prompt


def test_llm_tagger_allocates_reasoning_budget_for_gpt_oss_models() -> None:
    async def scenario() -> None:
        generator = FakeStructuredGenerator()
        tagger = LLMContentTagger(
            settings=Settings(tags_llm_prompt_version="test-tags-v2", tags_llm_model="gpt-oss"),
            llm_generator=generator,
        )

        await tagger.suggest(
            title="Edifier M90 listing",
            url=None,
            existing_tags=[],
            excerpt="Edifier M90 active speakers with LDAC and Hi-Res Audio support.",
            metadata={"media_type": "image", "source_filename": "listing.jpg"},
            max_tags=8,
        )

        model_config = generator.calls[0]["model_config"]
        assert model_config["reasoning_effort"] == "low"
        assert model_config["max_tokens"] == 4096

    asyncio.run(scenario())


def test_llm_tagger_filters_pdf_container_and_filename_tags() -> None:
    async def scenario() -> None:
        tagger = LLMContentTagger(
            settings=Settings(tags_llm_prompt_version="test-tags-v2"),
            llm_generator=FakeStructuredGenerator(
                {
                    "tags": [
                        {"name": "complex", "confidence": 0.95, "reasoning": "Internal kind."},
                        {"name": "Page_1", "confidence": 0.94, "reasoning": "Filename."},
                        {"name": "PDF", "confidence": 0.93, "reasoning": "File format."},
                        {
                            "name": "Web Design",
                            "confidence": 0.92,
                            "reasoning": "Course name in the certificate.",
                        },
                        {
                            "name": "Unity 3D",
                            "confidence": 0.90,
                            "reasoning": "Listed as a course module.",
                        },
                        {
                            "name": "Сертификат",
                            "confidence": 0.89,
                            "reasoning": "Document type in the text.",
                        },
                    ]
                }
            ),
        )

        suggestions = await tagger.suggest(
            title="Page_1.pdf",
            url=None,
            existing_tags=[],
            excerpt=(
                "# Page_1.pdf\n\n"
                "Юный IT- специалист\n"
                "Шиков Артем Алексеевич\n"
                "Успешно завершил(а) курс Web Design\n"
                "Модули: Unity 3D, Blender, Unreal Engine\n"
                "СЕРТИФИКАТ\n"
                "Tinkercad - 3D моделирование\n"
                "Gimp - Графическая обработка изображения\n"
                "SketchUp - 3D проектирование"
            ),
            metadata={
                "kind": "complex",
                "media_type": "document",
                "source_filename": "Page_1.pdf",
                "mime_type": "application/pdf",
            },
            max_tags=8,
        )

        assert [suggestion.name for suggestion in suggestions] == [
            "Web Design",
            "Unity 3D",
            "Сертификат",
        ]

    asyncio.run(scenario())


def test_service_existing_tag_candidates_prefer_relevant_and_active_tags() -> None:
    content_object = ContentObject(
        owner_user_id="user-1",
        slug="pgvector-indexing-benchmark",
        title="pgvector indexing benchmark",
        kind="simple",
        media_type="text",
        source_filename="pgvector.md",
        mime_type="text/markdown",
        storage_path="content-assets/object-1",
    )
    content_object.assets.append(
        ContentAsset(
            role="original",
            media_type="text",
            filename="pgvector.md",
            mime_type="text/markdown",
            size_bytes=128,
            storage_path="content-assets/object-1/source.md",
            text_content="PostgreSQL HNSW indexing and vector search notes.",
        )
    )
    postgresql = Tag(
        owner_user_id="user-1",
        name="PostgreSQL",
        slug="postgresql",
        description=None,
        tag_kind="technology",
        created_by_type="user",
        source="manual",
    )
    vacation = Tag(
        owner_user_id="user-1",
        name="Vacation Planning",
        slug="vacation-planning",
        description=None,
        tag_kind="topic",
        created_by_type="user",
        source="manual",
    )
    active = Tag(
        owner_user_id="user-1",
        name="Read Later",
        slug="read-later",
        description=None,
        tag_kind="status",
        created_by_type="user",
        source="manual",
    )

    candidates = TagsService._existing_tag_candidates(
        content_object=content_object,
        active_tags=[active],
        tags=[vacation, postgresql, active],
        max_tags=8,
    )

    assert [tag.name for tag in candidates] == ["Read Later", "PostgreSQL"]


def test_service_existing_tag_candidates_ignore_pdf_metadata_tags() -> None:
    content_object = ContentObject(
        owner_user_id="user-1",
        slug="page-1",
        title="Page_1.pdf",
        kind="complex",
        media_type="document",
        source_filename="Page_1.pdf",
        mime_type="application/pdf",
        storage_path="content-assets/object-1",
    )
    content_object.assets.append(
        ContentAsset(
            role="text",
            media_type="text",
            filename="Page_1.md",
            mime_type="text/markdown",
            size_bytes=256,
            storage_path="content-assets/object-1/text.md",
            text_content=(
                "# Page_1.pdf\n\n"
                "Успешно завершил(а) курс Web Design.\n"
                "СЕРТИФИКАТ.\n"
                "Unity 3D, Blender, Unreal Engine."
            ),
        )
    )
    pdf = Tag(
        owner_user_id="user-1",
        name="PDF",
        slug="pdf",
        description=None,
        tag_kind="format",
        created_by_type="llm",
        source="llm_auto_created",
    )
    filename = Tag(
        owner_user_id="user-1",
        name="Page_1",
        slug="page-1",
        description=None,
        tag_kind=None,
        created_by_type="llm",
        source="llm_auto_created",
    )
    certificate = Tag(
        owner_user_id="user-1",
        name="Сертификат",
        slug="sertifikat",
        description=None,
        tag_kind="document_type",
        created_by_type="user",
        source="manual",
    )

    candidates = TagsService._existing_tag_candidates(
        content_object=content_object,
        active_tags=[],
        tags=[pdf, filename, certificate],
        max_tags=8,
    )

    assert [tag.name for tag in candidates] == ["Сертификат"]


def test_service_llm_suggestions_store_metadata_thresholds_and_history(tmp_path: Path) -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        async with session_factory() as session:
            user = User(telegram_id="100600", display_name="User")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            content_service = ContentService(session, tmp_path / "content-storage")
            note = await content_service.create_note(
                owner_user_id=user.id,
                media_type="text",
                text="The paper benchmarks vLLM and KV-cache latency.",
                title="Inference benchmark",
                folder_path=None,
                tag_names=[],
                file_upload_ids=[],
            )

            settings = Settings(
                tags_llm_enabled=True,
                tags_llm_model="fake-tags",
                tags_llm_auto_apply_threshold=0.85,
                tags_llm_suggest_threshold=0.60,
                tags_llm_create_missing_tags=True,
            )
            generator = FakeStructuredGenerator(
                {
                    "tags": [
                        {
                            "name": "vLLM",
                            "confidence": 0.91,
                            "reasoning": "The note discusses vLLM serving.",
                        },
                        {
                            "name": "KV-cache",
                            "confidence": 0.70,
                            "reasoning": "KV-cache is a main topic.",
                        },
                        {
                            "name": "interesting",
                            "confidence": 0.20,
                            "reasoning": "Too generic and low confidence.",
                        },
                        {
                            "name": "vllm",
                            "confidence": 0.86,
                            "reasoning": "Duplicate slug.",
                        },
                    ]
                }
            )
            service = TagsService(session, settings=settings, llm_generator=generator)

            dry_run = await service.suggest_tags_for_content(
                owner_user_id=user.id,
                content_object_id=note.id,
                max_tags=8,
                persist=False,
            )
            assert [suggestion.slug for suggestion in dry_run] == ["vllm", "kv-cache"]
            assert "Taxonomy category:" not in generator.calls[0]["prompt"]
            assert list(await session.scalars(select(Tag))) == []

            persisted = await service.suggest_tags_for_content(
                owner_user_id=user.id,
                content_object_id=note.id,
                max_tags=8,
                persist=True,
            )
            assert [suggestion.slug for suggestion in persisted] == ["vllm", "kv-cache"]

            tags = sorted(await session.scalars(select(Tag)), key=lambda item: item.slug)
            assert [tag.slug for tag in tags] == ["kv-cache", "vllm"]
            assignments = sorted(
                await session.scalars(select(ContentTagAssignment)),
                key=lambda item: item.confidence or 0,
                reverse=True,
            )
            assert [assignment.status for assignment in assignments] == ["accepted", "suggested"]
            assert assignments[0].source_detail["model"] == "fake-tags"
            assert assignments[0].source_detail["prompt_version"] == "content_tags_v1"

            accepted = await service.accept_suggestion(
                owner_user_id=user.id,
                content_object_id=note.id,
                assignment_id=assignments[1].id,
                assigned_by_user_id=user.id,
            )
            assert accepted.status == "accepted"

            await service.remove_tag_from_content(
                owner_user_id=user.id,
                content_object_id=note.id,
                tag_id=tags[0].id,
                assigned_by_user_id=user.id,
            )
            history = list(await session.scalars(select(ContentTagAssignment)))
            assert {assignment.status for assignment in history} == {"accepted", "removed"}
            feedback = list(await session.scalars(select(ClassificationFeedback)))
            assert {item.action for item in feedback} >= {"accepted", "removed"}

    asyncio.run(scenario())


def test_service_llm_prompt_uses_content_context_and_existing_tag_candidates(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        async with session_factory() as session:
            user = User(telegram_id="100650", display_name="User")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            content_service = ContentService(session, tmp_path / "content-storage")
            note = await content_service.create_note(
                owner_user_id=user.id,
                media_type="text",
                text=(
                    "PostgreSQL indexing notes. Use pgvector for nearest-neighbor search. "
                    "Tune HNSW and IVFFlat indexes for recall and latency. "
                    + ("database retrieval " * 260)
                    + "TAIL_MARKER_SHOULD_BE_TRUNCATED"
                ),
                title="pgvector indexing benchmark",
                folder_path=None,
                tag_names=[],
                file_upload_ids=[],
            )

            service = TagsService(
                session,
                settings=Settings(tags_llm_enabled=True, tags_llm_model="fake-tags"),
                llm_generator=FakeStructuredGenerator(),
            )
            await service.create_tag(
                owner_user_id=user.id,
                name="PostgreSQL",
                description=None,
                tag_kind="technology",
                created_by_user_id=user.id,
                commit=False,
            )
            await service.create_tag(
                owner_user_id=user.id,
                name="Vacation Planning",
                description=None,
                tag_kind="topic",
                created_by_user_id=user.id,
                commit=False,
            )
            await session.commit()

            await service.suggest_tags_for_content(
                owner_user_id=user.id,
                content_object_id=note.id,
                max_tags=6,
                persist=False,
            )

            prompt = service.llm_generator.calls[0]["prompt"]
            assert "Title: pgvector indexing benchmark" in prompt
            assert "media_type" in prompt
            assert "Existing candidate tags: PostgreSQL" in prompt
            assert "Vacation Planning" not in prompt
            assert "PostgreSQL indexing notes" in prompt
            assert "TAIL_MARKER_SHOULD_BE_TRUNCATED" not in prompt
            assert "different levels of abstraction" in prompt
            assert "broad categories" in prompt
            assert "specific topics" in prompt
            assert "source, context, or confidence" in prompt

    asyncio.run(scenario())


def test_worker_processes_jobs_idempotently_and_fails_when_llm_disabled(tmp_path: Path) -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        async with session_factory() as session:
            user = User(telegram_id="100700", display_name="User")
            session.add(user)
            await session.commit()
            await session.refresh(user)
            content_service = ContentService(session, tmp_path / "content-storage")
            note = await content_service.create_note(
                owner_user_id=user.id,
                media_type="text",
                text="PostgreSQL indexing and vLLM serving notes.",
                title="Worker note",
                folder_path=None,
                tag_names=[],
                file_upload_ids=[],
            )
            enabled_settings = Settings(tags_llm_enabled=True, tags_llm_model="fake-tags")
            service = TagsService(
                session,
                settings=enabled_settings,
                llm_generator=FakeStructuredGenerator(
                    {
                        "tags": [
                            {
                                "name": "PostgreSQL",
                                "confidence": 0.88,
                                "reasoning": "Database topic.",
                            }
                        ]
                    }
                ),
            )
            job = await service.enqueue_content_tag_suggestions(
                owner_user_id=user.id,
                content_object_id=note.id,
            )
            await session.commit()

            processed = await TagsWorker(
                session,
                settings=enabled_settings,
                llm_generator=service.llm_generator,
            ).run_once(limit=10)
            assert processed == 1
            await session.refresh(job)
            assert job.status == "succeeded"
            assert len(list(await session.scalars(select(Tag)))) == 1
            assert len(list(await session.scalars(select(ContentTagAssignment)))) == 1

            retry_job = await service.enqueue_content_tag_suggestions(
                owner_user_id=user.id,
                content_object_id=note.id,
            )
            await session.commit()
            processed_again = await TagsWorker(
                session,
                settings=enabled_settings,
                llm_generator=service.llm_generator,
            ).run_once(limit=10)
            assert processed_again == 1
            await session.refresh(retry_job)
            assert retry_job.status == "succeeded"
            assert len(list(await session.scalars(select(Tag)))) == 1
            assert len(list(await session.scalars(select(ContentTagAssignment)))) == 1

            disabled_service = TagsService(
                session,
                settings=Settings(tags_llm_enabled=True),
                llm_generator=FakeStructuredGenerator(),
            )
            disabled_job = await disabled_service.enqueue_content_tag_suggestions(
                owner_user_id=user.id,
                content_object_id=note.id,
            )
            await session.commit()
            await TagsWorker(
                session,
                settings=Settings(tags_llm_enabled=False),
                llm_generator=FakeStructuredGenerator(),
            ).run_once(limit=10)
            await session.refresh(disabled_job)
            assert disabled_job.status == "failed"
            assert disabled_job.last_error == "LLM tag suggestions are disabled."

    asyncio.run(scenario())


def test_tag_jobs_trace_source_event_coalesce_and_skip_stale_content(tmp_path: Path) -> None:
    async def scenario() -> dict[str, object]:
        session_factory = await _prepare_database(_test_database_url())
        async with session_factory() as session:
            user = User(telegram_id="100720", display_name="User")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            note = await ContentService(session, tmp_path / "content-storage").create_note(
                owner_user_id=user.id,
                media_type="text",
                text="Initial tag text.",
                title="Traceable tag job",
                folder_path=None,
                tag_names=[],
                file_upload_ids=[],
            )
            content_object = await session.get(ContentObject, note.id)
            assert content_object is not None
            service = TagsService(
                session,
                settings=Settings(tags_llm_enabled=True, tags_llm_model="fake-tags"),
                llm_generator=FakeStructuredGenerator(),
            )
            first = await service.repository.enqueue_job(
                owner_user_id=user.id,
                content_object_id=note.id,
                job_type="suggest_content_tags",
                priority=10,
                source_event_id="event-1",
                correlation_id="correlation-1",
                content_updated_at_snapshot=content_object.updated_at,
            )
            first_snapshot = first.content_updated_at_snapshot
            second = await service.repository.enqueue_job(
                owner_user_id=user.id,
                content_object_id=note.id,
                job_type="suggest_content_tags",
                priority=90,
                source_event_id="event-2",
                correlation_id="correlation-2",
                content_updated_at_snapshot=content_object.updated_at,
            )
            content_object.title = "Updated after tag enqueue"
            await session.flush()
            first.content_updated_at_snapshot = first_snapshot
            first.status = "processing"
            first.attempts = 1
            await service.process_job(first)
            await session.commit()
            return {
                "same_job": first.id == second.id,
                "priority": first.priority,
                "source_event_id": first.source_event_id,
                "correlation_id": first.correlation_id,
                "status": first.status,
            }

    result = asyncio.run(scenario())

    assert result == {
        "same_job": True,
        "priority": 90,
        "source_event_id": "event-2",
        "correlation_id": "correlation-2",
        "status": "stale",
    }
