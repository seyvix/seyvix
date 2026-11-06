import asyncio
import os

# Tests must not depend on a developer's local .env or proxy settings.
os.environ["SEYVIX_IGNORE_ENV_FILES"] = "1"
for _proxy_var in (
    "ALL_PROXY",
    "all_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
):
    os.environ.pop(_proxy_var, None)
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import Base
from app.main import app
from app.models import import_all_models
from app.platform.storage.local import LocalVolumeStorage

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"
TELEGRAM_INTERNAL_TOKEN = "test-internal-token-0123456789abcdef0123"


async def prepare_database(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Recreate the schema from the ORM models (what the baseline migration produces)."""
    import_all_models()
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    # NullPool: tests touch the DB both from the TestClient's loop and via asyncio.run();
    # pooled asyncpg connections must never cross event loops.
    return async_sessionmaker(
        create_async_engine(database_url, poolclass=NullPool), expire_on_commit=False
    )


def require_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable database for DB-resetting tests.")
    return database_url


def configure_test_environment() -> None:
    os.environ["TELEGRAM_BOT_TOKEN"] = TELEGRAM_BOT_TOKEN
    os.environ["TELEGRAM_INTERNAL_TOKEN"] = TELEGRAM_INTERNAL_TOKEN
    os.environ["ACCESS_MODE"] = "open"
    os.environ["STORAGE_BACKEND"] = "local"
    get_settings.cache_clear()


@pytest.fixture
def content_client(tmp_path: Path) -> Iterator[TestClient]:
    """API client on a fresh database with storage in a temporary directory."""
    configure_test_environment()
    database_url = require_database_url()
    try:
        session_factory = asyncio.run(prepare_database(database_url))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for API tests: {exc}")

    previous_storage = app.state.storage
    app.state.session_factory = session_factory  # the lifespan keeps an injected factory
    app.state.storage = LocalVolumeStorage(tmp_path / "content-storage")
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.state.session_factory = None
        app.state.storage = previous_storage
        get_settings.cache_clear()
