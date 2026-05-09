from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


def _test_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable database for migration tests.")
    return database_url


async def _reset_public_schema(database_url: str) -> None:
    engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await engine.dispose()


async def _database_state(database_url: str) -> tuple[set[str], str | None, bool]:
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        tables = set(
            await connection.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        )
        current_revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        vector_extension = bool(
            await connection.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        )
    await engine.dispose()
    return tables, current_revision, vector_extension


def test_alembic_upgrade_head_builds_current_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _test_database_url()
    url = make_url(database_url)
    monkeypatch.setenv("POSTGRES_HOST", str(url.host or "localhost"))
    monkeypatch.setenv("POSTGRES_PORT", str(url.port or 5432))
    monkeypatch.setenv("POSTGRES_DB", str(url.database))
    monkeypatch.setenv("POSTGRES_USER", str(url.username))
    monkeypatch.setenv("POSTGRES_PASSWORD", str(url.password))
    get_settings.cache_clear()

    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    head_revision = ScriptDirectory.from_config(config).get_current_head()

    try:
        asyncio.run(_reset_public_schema(database_url))
        command.upgrade(config, "head")
        tables, current_revision, vector_extension = asyncio.run(_database_state(database_url))
    finally:
        asyncio.run(_reset_public_schema(database_url))
        get_settings.cache_clear()

    assert current_revision == head_revision
    assert vector_extension is True
    assert {
        "users",
        "auth_sessions",
        "content_objects",
        "content_assets",
        "snapshot_jobs",
        "tags",
        "taxonomy_categories",
        "taxonomy_content_assignments",
        "vectorization_sources",
        "vectorization_embeddings",
    } <= tables
