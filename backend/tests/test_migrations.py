"""The alembic baseline must build exactly the schema the ORM models describe."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.database import Base
from app.models import import_all_models

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable database for migration tests.")
    return database_url


async def _reset_schema(database_url: str) -> None:
    engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


async def _schema_drift(database_url: str) -> list[object]:
    import_all_models()

    def compare(connection: Connection) -> list[object]:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return list(compare_metadata(context, Base.metadata))

    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        diff = await connection.run_sync(compare)
    await engine.dispose()
    return diff


async def _notification_on_job_insert(database_url: str) -> str:
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
    listener = await asyncpg.connect(dsn)
    writer = await asyncpg.connect(dsn)
    received: asyncio.Queue[str] = asyncio.Queue()
    await listener.add_listener("seyvix_jobs", lambda *args: received.put_nowait(args[-1]))
    try:
        await writer.execute(
            "INSERT INTO events (id, name, version, occurred_at, correlation_id, entity_id, "
            "payload, created_at) VALUES ('e1', 'content.object.created', 1, now(), 'c', 'x', "
            "'{}', now())"
        )
        await writer.execute(
            "INSERT INTO event_deliveries (id, event_id, consumer, status, priority, attempts, "
            "max_attempts, run_after, created_at, updated_at) VALUES "
            "('d1', 'e1', 'snapshots', 'pending', 100, 0, 5, now(), now(), now())"
        )
        return await asyncio.wait_for(received.get(), timeout=5)
    finally:
        await listener.close()
        await writer.close()


def test_baseline_matches_models_and_installs_notify_triggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    url = make_url(database_url)
    monkeypatch.setenv("POSTGRES_HOST", str(url.host or "localhost"))
    monkeypatch.setenv("POSTGRES_PORT", str(url.port or 5432))
    monkeypatch.setenv("POSTGRES_DB", str(url.database))
    monkeypatch.setenv("POSTGRES_USER", str(url.username))
    monkeypatch.setenv("POSTGRES_PASSWORD", str(url.password))
    get_settings.cache_clear()
    config = Config(str(PROJECT_ROOT / "alembic.ini"))

    try:
        asyncio.run(_reset_schema(database_url))
        command.upgrade(config, "head")
        drift = asyncio.run(_schema_drift(database_url))
        channel_payload = asyncio.run(_notification_on_job_insert(database_url))
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        asyncio.run(_reset_schema(database_url))
        get_settings.cache_clear()

    assert drift == []
    assert channel_payload == "event_deliveries"
