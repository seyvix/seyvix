"""Owner admin panel: access control, system overview and dead-letter management."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.config import get_settings
from app.main import app
from app.platform.events.models import EventDelivery
from app.platform.jobs import JOB_FAILED, JOB_PENDING
from tests.test_content import _auth_headers, _create_text_note

ADMIN_ID = 424242


@pytest.fixture
def admin_headers(content_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", str(ADMIN_ID))
    get_settings.cache_clear()
    return _auth_headers(content_client, telegram_id=ADMIN_ID)


def run_db(coro_factory):  # type: ignore[no-untyped-def]
    async def run():  # type: ignore[no-untyped-def]
        async with app.state.session_factory() as session:
            result = await coro_factory(session)
            await session.commit()
            return result

    return asyncio.run(run())


def test_non_admin_is_forbidden(content_client: TestClient, admin_headers: dict[str, str]) -> None:
    user_headers = _auth_headers(content_client, telegram_id=1001)

    assert content_client.get("/api/v1/admin/overview", headers=user_headers).status_code == 403


def test_overview_reports_system_queues_and_totals(
    content_client: TestClient, admin_headers: dict[str, str]
) -> None:
    _create_text_note(content_client, admin_headers, title="Hello", text="admin overview")

    response = content_client.get("/api/v1/admin/overview", headers=admin_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totals"]["notes"] == 1
    assert body["totals"]["users"] == 1
    assert body["database"]["size_bytes"] > 0
    assert body["host"]["disk_total_bytes"] > 0
    assert body["config"]["access_mode"] == "open"
    queues = {queue["queue"]: queue for queue in body["queues"]}
    assert {"snapshot_jobs", "vectorization_jobs", "tagging_jobs"} <= set(queues)
    # The new note produced a pending delivery for the snapshots consumer.
    assert queues["events:snapshots"]["pending"] == 1


def test_failed_deliveries_can_be_listed_retried_and_purged(
    content_client: TestClient, admin_headers: dict[str, str]
) -> None:
    _create_text_note(content_client, admin_headers, title="One", text="dead letter")
    run_db(
        lambda s: s.execute(
            update(EventDelivery).values(status=JOB_FAILED, attempts=5, last_error="boom")
        )
    )
    queue = "events:snapshots"

    listed = content_client.get(
        f"/api/v1/admin/queues/{queue}/jobs?status=failed", headers=admin_headers
    ).json()
    assert listed["total"] == 1
    assert listed["items"][0]["last_error"] == "boom"

    retried = content_client.post(
        f"/api/v1/admin/queues/{queue}/retry", json={"ids": None}, headers=admin_headers
    )
    assert retried.json() == {"count": 1}
    statuses = run_db(lambda s: s.scalars(select(EventDelivery.status)))
    assert list(statuses) == [JOB_PENDING]

    run_db(lambda s: s.execute(update(EventDelivery).values(status=JOB_FAILED)))
    purged = content_client.delete(f"/api/v1/admin/queues/{queue}/failed", headers=admin_headers)
    assert purged.json() == {"count": 1}


def test_unknown_queue_is_404(content_client: TestClient, admin_headers: dict[str, str]) -> None:
    response = content_client.get("/api/v1/admin/queues/users/jobs", headers=admin_headers)

    assert response.status_code == 404
