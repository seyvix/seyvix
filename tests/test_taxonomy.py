import asyncio
import hashlib
import hmac
import os
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import build_session_factory
from app.modules.content.models import ContentObject
from app.modules.content.service import ContentService
from app.modules.search.schemas import SemanticSearchResult
from app.modules.taxonomy.service import TaxonomyService
from app.modules.vectorization.contracts import build_taxonomy_category_profile_vector_subject
from app.modules.vectorization.worker import VectorizationWorker

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


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
    response = client.post(
        "/api/v1/auth/telegram-login",
        json=_telegram_payload(telegram_id),
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_category(
    client: TestClient,
    headers: dict[str, str],
    *,
    slug: str,
    name: str,
    parent_id: str | None = None,
    sort_order: int = 100,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/taxonomy/categories",
        headers=headers,
        json={
            "parent_id": parent_id,
            "slug": slug,
            "name": name,
            "description": f"{name} description",
            "sort_order": sort_order,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_note(client: TestClient, headers: dict[str, str], title: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/notes",
        headers=headers,
        json={"media_type": "text", "title": title, "text": f"{title} body"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _worker_session_factory():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("Set TEST_DATABASE_URL to run DB-backed taxonomy tests.")
    return build_session_factory(database_url)


def _template_paths(items: list[dict[str, object]]) -> set[str]:
    paths: set[str] = set()
    for item in items:
        paths.add(str(item["path"]))
        paths.update(_template_paths(item["children"]))  # type: ignore[arg-type]
    return paths


def test_category_tree_validation_and_archive_behavior(content_client: TestClient) -> None:
    headers = _auth_headers(content_client)

    ai = _create_category(content_client, headers, slug="ai", name="AI", sort_order=20)
    _create_category(
        content_client,
        headers,
        slug="programming",
        name="Programming",
        sort_order=10,
    )
    llm = _create_category(
        content_client,
        headers,
        parent_id=ai["id"],
        slug="llm",
        name="LLM",
    )
    inference = _create_category(
        content_client,
        headers,
        parent_id=llm["id"],
        slug="inference",
        name="Inference",
    )

    assert inference["path"] == "ai/llm/inference"
    assert inference["depth"] == 2

    tree_response = content_client.get("/api/v1/taxonomy/categories/tree", headers=headers)
    assert tree_response.status_code == 200
    tree = tree_response.json()
    assert [item["path"] for item in tree] == ["programming", "ai"]
    ai_node = tree[1]
    assert ai_node["children"][0]["path"] == "ai/llm"
    assert ai_node["children"][0]["children"][0]["path"] == "ai/llm/inference"

    limited_response = content_client.get(
        f"/api/v1/taxonomy/categories/tree?root_id={ai['id']}&max_depth=1",
        headers=headers,
    )
    assert limited_response.status_code == 200
    assert limited_response.json()[0]["children"][0]["children"] == []

    duplicate_response = content_client.post(
        "/api/v1/taxonomy/categories",
        headers=headers,
        json={"slug": "llm", "name": "Other LLM", "parent_id": ai["id"]},
    )
    assert duplicate_response.status_code == 409

    invalid_response = content_client.post(
        "/api/v1/taxonomy/categories",
        headers=headers,
        json={"slug": "bad/slug", "name": "Bad"},
    )
    assert invalid_response.status_code == 422

    slug_update_response = content_client.patch(
        f"/api/v1/taxonomy/categories/{llm['id']}",
        headers=headers,
        json={"slug": "large-language-models"},
    )
    assert slug_update_response.status_code == 409

    archive_child = content_client.delete(
        f"/api/v1/taxonomy/categories/{inference['id']}",
        headers=headers,
    )
    assert archive_child.status_code == 204
    hidden_tree = content_client.get("/api/v1/taxonomy/categories/tree", headers=headers).json()
    assert hidden_tree[1]["children"][0]["children"] == []


def test_profile_manual_assignment_history_and_ownership(content_client: TestClient) -> None:
    headers = _auth_headers(content_client)
    other_headers = _auth_headers(content_client, telegram_id=200600)
    ai = _create_category(content_client, headers, slug="ai", name="AI")
    ml = _create_category(content_client, headers, slug="ml", name="ML")
    other_category = _create_category(content_client, other_headers, slug="private", name="Private")
    note = _create_note(content_client, headers, "Assignment target")

    profile_response = content_client.put(
        f"/api/v1/taxonomy/categories/{ai['id']}/profile",
        headers=headers,
        json={
            "summary": "Materials about AI systems.",
            "keywords": ["ai", "llm"],
            "positive_examples": ["LLM inference note"],
            "negative_examples": ["personal todo"],
        },
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["keywords"] == ["ai", "llm"]
    assert (
        content_client.put(
            f"/api/v1/taxonomy/categories/{other_category['id']}/profile",
            headers=headers,
            json={"summary": "Nope"},
        ).status_code
        == 404
    )

    first_assignment = content_client.post(
        f"/api/v1/taxonomy/content/{note['id']}/assignments",
        headers=headers,
        json={"category_id": ai["id"], "reasoning": "Manual assignment."},
    )
    assert first_assignment.status_code == 201, first_assignment.text
    assert first_assignment.json()["status"] == "accepted"
    assert first_assignment.json()["is_current"] is True
    assert first_assignment.json()["category_path_snapshot"] == "ai"

    second_assignment = content_client.post(
        f"/api/v1/taxonomy/content/{note['id']}/assignments",
        headers=headers,
        json={"category_id": ml["id"], "reasoning": "Better fit."},
    )
    assert second_assignment.status_code == 201

    current_response = content_client.get(
        f"/api/v1/taxonomy/content/{note['id']}/category",
        headers=headers,
    )
    assert current_response.status_code == 200
    assert current_response.json()["category_id"] == ml["id"]

    history_response = content_client.get(
        f"/api/v1/taxonomy/content/{note['id']}/assignments",
        headers=headers,
    )
    history = history_response.json()
    assert [item["status"] for item in history] == ["accepted", "overridden"]
    assert sum(1 for item in history if item["is_current"]) == 1

    reject_response = content_client.post(
        f"/api/v1/taxonomy/content/{note['id']}/assignments/{second_assignment.json()['id']}/reject",
        headers=headers,
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert reject_response.json()["is_current"] is False
    no_current_response = content_client.get(
        f"/api/v1/taxonomy/content/{note['id']}/category",
        headers=headers,
    )
    assert no_current_response.json() is None

    accept_response = content_client.post(
        f"/api/v1/taxonomy/content/{note['id']}/assignments/{first_assignment.json()['id']}/accept",
        headers=headers,
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["category_id"] == ai["id"]
    assert accept_response.json()["is_current"] is True

    cross_owner_response = content_client.post(
        f"/api/v1/taxonomy/content/{note['id']}/assignments",
        headers=headers,
        json={"category_id": other_category["id"]},
    )
    assert cross_owner_response.status_code == 404


def test_templates_initialize_user_taxonomy_and_module_registration(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    templates_response = content_client.get("/api/v1/taxonomy/templates", headers=headers)
    assert templates_response.status_code == 200
    assert {"default", "developer"}.issubset(
        {template["slug"] for template in templates_response.json()}
    )

    developer_response = content_client.get(
        "/api/v1/taxonomy/templates/developer",
        headers=headers,
    )
    assert developer_response.status_code == 200
    assert "programming/python" in _template_paths(developer_response.json()["tree"])

    initialize_response = content_client.post(
        "/api/v1/taxonomy/initialize",
        headers=headers,
        json={"template_slug": "developer"},
    )
    assert initialize_response.status_code == 201, initialize_response.text
    payload = initialize_response.json()
    assert payload["template_slug"] == "developer"
    assert payload["created_categories_count"] >= 20
    assert payload["created_profiles_count"] == payload["created_categories_count"]

    tree_response = content_client.get("/api/v1/taxonomy/categories/tree", headers=headers)
    assert tree_response.status_code == 200
    assert any(item["path"] == "inbox" and item["is_system"] for item in tree_response.json())

    second_initialize = content_client.post(
        "/api/v1/taxonomy/initialize",
        headers=headers,
        json={"template_slug": "default"},
    )
    assert second_initialize.status_code == 409

    modules_response = content_client.get("/api/v1/modules", headers=headers)
    assert modules_response.status_code == 200
    assert "taxonomy" in {module["name"] for module in modules_response.json()}


def test_content_creation_uses_taxonomy_assignment_not_legacy_category_id(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    note_response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "media_type": "text",
            "title": "Taxonomy note",
            "text": "Taxonomy note body",
            "folder_path": "work/research",
        },
    )
    assert note_response.status_code == 201, note_response.text
    note = note_response.json()
    assert "folder" not in note
    assert note["taxonomy_category"]["path"] == "work/research"

    assignment_response = content_client.get(
        f"/api/v1/taxonomy/content/{note['id']}/category",
        headers=headers,
    )
    assert assignment_response.status_code == 200
    assert assignment_response.json()["category_path_snapshot"] == "work/research"

    async def load_content_object() -> ContentObject | None:
        async with content_client.app.state.session_factory() as session:
            return await session.scalar(select(ContentObject).where(ContentObject.id == note["id"]))

    content_object = content_client.portal.call(load_content_object)
    assert content_object is not None
    assert content_object.category_id is None


def test_end_to_end_taxonomy_cutover_flow(content_client: TestClient) -> None:
    headers = _auth_headers(content_client)

    initialize_response = content_client.post(
        "/api/v1/taxonomy/initialize",
        headers=headers,
        json={"template_slug": "developer"},
    )
    assert initialize_response.status_code == 201, initialize_response.text

    tree_response = content_client.get("/api/v1/taxonomy/categories/tree", headers=headers)
    assert tree_response.status_code == 200
    tree = tree_response.json()
    programming = next(item for item in tree if item["path"] == "programming")
    python_category = next(
        item for item in programming["children"] if item["path"] == "programming/python"
    )

    custom_response = content_client.post(
        "/api/v1/taxonomy/categories",
        headers=headers,
        json={
            "parent_id": programming["id"],
            "slug": "inference",
            "name": "Inference",
            "description": "Runtime serving and inference notes.",
            "sort_order": 15,
        },
    )
    assert custom_response.status_code == 201, custom_response.text
    custom_category = custom_response.json()
    assert custom_category["path"] == "programming/inference"

    create_profile_response = content_client.put(
        f"/api/v1/taxonomy/categories/{custom_category['id']}/profile",
        headers=headers,
        json={
            "summary": "Initial inference profile.",
            "keywords": ["inference"],
            "positive_examples": ["serving note"],
            "negative_examples": ["frontend note"],
        },
    )
    assert create_profile_response.status_code == 200
    update_profile_response = content_client.put(
        f"/api/v1/taxonomy/categories/{custom_category['id']}/profile",
        headers=headers,
        json={
            "summary": "Updated inference profile.",
            "keywords": ["inference", "serving"],
            "positive_examples": ["latency note"],
            "negative_examples": ["css note"],
        },
    )
    assert update_profile_response.status_code == 200
    assert update_profile_response.json()["summary"] == "Updated inference profile."

    note_response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"media_type": "text", "title": "Flow note", "text": "Flow note body"},
    )
    assert note_response.status_code == 201, note_response.text
    note = note_response.json()
    assert "folder" not in note
    assert note["taxonomy_category"] is None

    first_assignment_response = content_client.post(
        f"/api/v1/taxonomy/content/{note['id']}/assignments",
        headers=headers,
        json={"category_id": custom_category["id"], "reasoning": "Manual flow assignment."},
    )
    assert first_assignment_response.status_code == 201, first_assignment_response.text
    first_assignment = first_assignment_response.json()
    assert first_assignment["is_current"] is True
    assert first_assignment["category_path_snapshot"] == "programming/inference"

    current_response = content_client.get(
        f"/api/v1/taxonomy/content/{note['id']}/category",
        headers=headers,
    )
    assert current_response.status_code == 200
    assert current_response.json()["id"] == first_assignment["id"]

    second_assignment_response = content_client.post(
        f"/api/v1/taxonomy/content/{note['id']}/assignments",
        headers=headers,
        json={"category_id": python_category["id"], "reasoning": "Manual reassignment."},
    )
    assert second_assignment_response.status_code == 201, second_assignment_response.text
    second_assignment = second_assignment_response.json()
    assert second_assignment["category_path_snapshot"] == "programming/python"

    history_response = content_client.get(
        f"/api/v1/taxonomy/content/{note['id']}/assignments",
        headers=headers,
    )
    assert history_response.status_code == 200
    history = history_response.json()
    by_id = {item["id"]: item for item in history}
    assert by_id[first_assignment["id"]]["status"] == "overridden"
    assert by_id[first_assignment["id"]]["is_current"] is False
    assert by_id[second_assignment["id"]]["status"] == "accepted"
    assert by_id[second_assignment["id"]]["is_current"] is True

    get_note_response = content_client.get(f"/api/v1/notes/{note['slug']}", headers=headers)
    assert get_note_response.status_code == 200
    get_note_payload = get_note_response.json()
    assert "folder" not in get_note_payload
    assert get_note_payload["taxonomy_category"]["path"] == "programming/python"

    async def load_content_object() -> ContentObject | None:
        async with content_client.app.state.session_factory() as session:
            return await session.scalar(select(ContentObject).where(ContentObject.id == note["id"]))

    content_object = content_client.portal.call(load_content_object)
    assert content_object is not None
    assert content_object.category_id is None


def test_taxonomy_search_breadcrumbs_restore_and_profile_document(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    ai = _create_category(content_client, headers, slug="ai", name="AI")
    llm = _create_category(content_client, headers, parent_id=ai["id"], slug="llm", name="LLM")
    inference = _create_category(
        content_client,
        headers,
        parent_id=llm["id"],
        slug="inference",
        name="Inference",
    )
    _create_category(content_client, headers, slug="personal", name="Personal")

    search_response = content_client.get(
        "/api/v1/taxonomy/categories/search?q=infer",
        headers=headers,
    )
    assert search_response.status_code == 200
    assert [item["path"] for item in search_response.json()] == ["ai/llm/inference"]

    breadcrumbs_response = content_client.get(
        f"/api/v1/taxonomy/categories/{inference['id']}/breadcrumbs",
        headers=headers,
    )
    assert breadcrumbs_response.status_code == 200
    assert breadcrumbs_response.json() == [
        {"id": ai["id"], "name": "AI", "path": "ai"},
        {"id": llm["id"], "name": "LLM", "path": "ai/llm"},
        {"id": inference["id"], "name": "Inference", "path": "ai/llm/inference"},
    ]

    archive_response = content_client.delete(
        f"/api/v1/taxonomy/categories/{inference['id']}",
        headers=headers,
    )
    assert archive_response.status_code == 204
    assert (
        content_client.get("/api/v1/taxonomy/categories/search?q=infer", headers=headers).json()
        == []
    )

    restore_response = content_client.post(
        f"/api/v1/taxonomy/categories/{inference['id']}/restore",
        headers=headers,
    )
    assert restore_response.status_code == 200
    assert restore_response.json()["is_archived"] is False

    profile_response = content_client.put(
        f"/api/v1/taxonomy/categories/{inference['id']}/profile",
        headers=headers,
        json={
            "summary": "Serving, latency, throughput, batching, and KV-cache.",
            "keywords": ["vllm", "inference", "serving", "kv-cache"],
            "positive_examples": [
                "article about speculative decoding",
                "note about continuous batching",
            ],
            "negative_examples": ["LLM model architecture", "model training"],
        },
    )
    assert profile_response.status_code == 200

    async def build_document() -> str:
        async with content_client.app.state.session_factory() as session:
            service = TaxonomyService(session)
            return await service.build_category_profile_document(
                owner_user_id=str(ai["owner_user_id"]),
                category_id=str(inference["id"]),
            )

    document = content_client.portal.call(build_document)
    assert document == (
        "Path: AI / LLM / Inference\n"
        "Name: Inference\n"
        "Description: Inference description\n"
        "Summary: Serving, latency, throughput, batching, and KV-cache.\n"
        "Keywords: vllm, inference, serving, kv-cache\n"
        "Positive examples:\n"
        "- article about speculative decoding\n"
        "- note about continuous batching\n"
        "Negative examples:\n"
        "- LLM model architecture\n"
        "- model training"
    )

    async def build_subject_external_id() -> str:
        async with content_client.app.state.session_factory() as session:
            service = TaxonomyService(session)
            subject = await service.build_category_profile_vector_subject(
                owner_user_id=str(ai["owner_user_id"]),
                category_id=str(inference["id"]),
            )
            expected = build_taxonomy_category_profile_vector_subject(
                owner_user_id=str(ai["owner_user_id"]),
                category_id=str(inference["id"]),
                category_path="ai/llm/inference",
                category_depth=2,
                source_text=document,
                source_updated_at=subject.source_updated_at,
            )
            assert subject == expected
            return subject.external_id

    assert (
        content_client.portal.call(build_subject_external_id)
        == f"taxonomy_category_profile:{inference['id']}"
    )


def test_content_classification_input_contract(content_client: TestClient) -> None:
    headers = _auth_headers(content_client)
    note_response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "media_type": "text",
            "title": "Classification target",
            "text": "First line for classification.\nSecond line has useful details.",
            "tag_names": ["AI", "draft"],
        },
    )
    assert note_response.status_code == 201, note_response.text
    note = note_response.json()

    async def build_input_for_owner() -> dict[str, object]:
        async with content_client.app.state.session_factory() as session:
            content_object = await session.scalar(
                select(ContentObject).where(ContentObject.id == note["id"])
            )
            assert content_object is not None
            service = ContentService(session, content_client.app.state.content_storage_root)
            classification_input = await service.build_classification_input(
                owner_user_id=content_object.owner_user_id,
                content_object_id=content_object.id,
            )
            return classification_input.model_dump(mode="json")

    payload = content_client.portal.call(build_input_for_owner)
    assert payload["content_object_id"] == note["id"]
    assert payload["title"] == "Classification target"
    assert (
        payload["text_excerpt"] == "First line for classification.\nSecond line has useful details."
    )
    assert payload["url"] is None
    assert payload["tags"] == ["ai", "draft"]
    assert payload["metadata"]["kind"] == "simple"
    assert payload["metadata"]["media_type"] == "text"
    assert payload["created_at"] == note["created_at"]


class _FakeSemanticSearchService:
    def __init__(self, results: list[SemanticSearchResult]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    async def semantic_search(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int,
        source: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> list[SemanticSearchResult]:
        self.calls.append(
            {
                "owner_user_id": owner_user_id,
                "query": query,
                "limit": limit,
                "source": source,
                "source_type": source_type,
                "source_id": source_id,
            }
        )
        return self.results[:limit]


def test_taxonomy_semantic_classification_assigns_proposes_and_preserves_history(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client, telegram_id=300900)
    inference = _create_category(content_client, headers, slug="inference", name="Inference")
    training = _create_category(content_client, headers, slug="training", name="Training")
    manual = _create_category(content_client, headers, slug="manual", name="Manual")
    high_note = _create_note(content_client, headers, "vLLM latency")
    medium_note = _create_note(content_client, headers, "Model training")
    low_note = _create_note(content_client, headers, "Shopping list")

    manual_assignment = content_client.post(
        f"/api/v1/taxonomy/content/{high_note['id']}/assignments",
        headers=headers,
        json={"category_id": manual["id"], "reasoning": "Manual override."},
    )
    assert manual_assignment.status_code == 201, manual_assignment.text

    async def scenario() -> tuple[dict[str, object], dict[str, object], object, list[str], str]:
        async with content_client.app.state.session_factory() as session:
            service = TaxonomyService(session)
            high_search = _FakeSemanticSearchService(
                [
                    SemanticSearchResult(
                        source="taxonomy",
                        source_type="category_profile",
                        source_id=str(inference["id"]),
                        external_id=f"taxonomy_category_profile:{inference['id']}",
                        chunk_id="chunk-high",
                        chunk_external_id="taxonomy:chunk:0",
                        text="Inference profile",
                        metadata={"category_path": "inference"},
                        distance=0.15,
                        score=0.85,
                    ),
                    SemanticSearchResult(
                        source="taxonomy",
                        source_type="category_profile",
                        source_id=str(training["id"]),
                        external_id=f"taxonomy_category_profile:{training['id']}",
                        chunk_id="chunk-alt",
                        chunk_external_id="taxonomy:chunk:1",
                        text="Training profile",
                        metadata={"category_path": "training"},
                        distance=0.25,
                        score=0.75,
                    ),
                ]
            )
            high = await service.classify_content_object(
                owner_user_id=str(inference["owner_user_id"]),
                content_object_id=str(high_note["id"]),
                semantic_search_service=high_search,
            )

            medium_search = _FakeSemanticSearchService(
                [
                    SemanticSearchResult(
                        source="taxonomy",
                        source_type="category_profile",
                        source_id=str(training["id"]),
                        external_id=f"taxonomy_category_profile:{training['id']}",
                        chunk_id="chunk-medium",
                        chunk_external_id="taxonomy:chunk:2",
                        text="Training profile",
                        metadata={},
                        distance=0.35,
                        score=0.65,
                    )
                ]
            )
            medium = await service.classify_content_object(
                owner_user_id=str(training["owner_user_id"]),
                content_object_id=str(medium_note["id"]),
                semantic_search_service=medium_search,
            )

            low_search = _FakeSemanticSearchService(
                [
                    SemanticSearchResult(
                        source="taxonomy",
                        source_type="category_profile",
                        source_id=str(training["id"]),
                        external_id=f"taxonomy_category_profile:{training['id']}",
                        chunk_id="chunk-low",
                        chunk_external_id="taxonomy:chunk:3",
                        text="Training profile",
                        metadata={},
                        distance=0.55,
                        score=0.45,
                    )
                ]
            )
            low = await service.classify_content_object(
                owner_user_id=str(training["owner_user_id"]),
                content_object_id=str(low_note["id"]),
                semantic_search_service=low_search,
            )

            calls = [
                str(high_search.calls[0]["source"]),
                str(high_search.calls[0]["source_type"]),
            ]
            assignments = await service.list_assignments(
                owner_user_id=str(inference["owner_user_id"]),
                content_object_id=str(high_note["id"]),
            )
            return (
                TaxonomyService.assignment_response(high).model_dump(mode="json"),
                TaxonomyService.assignment_response(medium).model_dump(mode="json"),
                low,
                calls,
                ",".join(assignment.status for assignment in assignments),
            )

    high, medium, low, filters, history_statuses = content_client.portal.call(scenario)

    assert high["status"] == "accepted"
    assert high["assigned_by"] == "system"
    assert high["category_id"] == inference["id"]
    assert high["confidence"] == 0.85
    assert high["alternatives"][0]["category_id"] == inference["id"]
    assert high["alternatives"][1]["category_id"] == training["id"]
    assert medium["status"] == "proposed"
    assert medium["category_id"] == training["id"]
    assert low is None
    assert filters == ["taxonomy", "category_profile"]
    assert "overridden" in history_statuses


def test_taxonomy_classify_endpoint_uses_semantic_assignment_flow(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client, telegram_id=301000)
    category = _create_category(content_client, headers, slug="inference", name="Inference")
    profile_response = content_client.put(
        f"/api/v1/taxonomy/categories/{category['id']}/profile",
        headers=headers,
        json={
            "summary": "Runtime serving latency and vLLM inference.",
            "keywords": ["vllm", "latency"],
            "positive_examples": ["vLLM latency note"],
            "negative_examples": [],
        },
    )
    assert profile_response.status_code == 200, profile_response.text
    note = _create_note(content_client, headers, "Endpoint classification")

    enqueue = content_client.post(
        "/api/v1/vectorization/index",
        headers=headers,
        json={
            "source": "taxonomy",
            "source_type": "category_profile",
            "source_id": category["id"],
        },
    )
    assert enqueue.status_code == 202, enqueue.text

    async def run_worker() -> int:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            return await VectorizationWorker(session).run_once(limit=10)

    assert asyncio.run(run_worker()) == 1

    previous_high = os.environ.get("TAXONOMY_CLASSIFICATION_HIGH_THRESHOLD")
    previous_medium = os.environ.get("TAXONOMY_CLASSIFICATION_MEDIUM_THRESHOLD")
    os.environ["TAXONOMY_CLASSIFICATION_HIGH_THRESHOLD"] = "-1"
    os.environ["TAXONOMY_CLASSIFICATION_MEDIUM_THRESHOLD"] = "-1"
    get_settings.cache_clear()
    try:
        endpoint_response = content_client.post(
            f"/api/v1/taxonomy/content/{note['id']}/classify",
            headers=headers,
        )
    finally:
        if previous_high is None:
            os.environ.pop("TAXONOMY_CLASSIFICATION_HIGH_THRESHOLD", None)
        else:
            os.environ["TAXONOMY_CLASSIFICATION_HIGH_THRESHOLD"] = previous_high
        if previous_medium is None:
            os.environ.pop("TAXONOMY_CLASSIFICATION_MEDIUM_THRESHOLD", None)
        else:
            os.environ["TAXONOMY_CLASSIFICATION_MEDIUM_THRESHOLD"] = previous_medium
        get_settings.cache_clear()

    assert endpoint_response.status_code == 200, endpoint_response.text
    assert endpoint_response.json()["status"] == "accepted"
    assert endpoint_response.json()["assigned_by"] == "system"
    assert endpoint_response.json()["category_id"] == category["id"]
