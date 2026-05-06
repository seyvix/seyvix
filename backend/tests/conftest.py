import asyncio
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base, build_session_factory  # noqa: E402
from app.main import app  # noqa: E402

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


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
def content_client(tmp_path: Path) -> Iterator[TestClient]:
    os.environ["TELEGRAM_BOT_TOKEN"] = TELEGRAM_BOT_TOKEN
    get_settings.cache_clear()
    database_url = _test_database_url()
    try:
        app.state.session_factory = asyncio.run(_prepare_database(database_url))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for content tests: {exc}")

    app.state.content_storage_root = tmp_path / "content-storage"
    app.state.storage_backend = None
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()
