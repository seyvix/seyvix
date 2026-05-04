import pytest
from app.core.database import NAMING_CONVENTION, Base, build_session_factory, get_session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_base_metadata_uses_stable_naming_convention() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert NAMING_CONVENTION["ix"] == "ix_%(column_0_label)s"
    assert NAMING_CONVENTION["pk"] == "pk_%(table_name)s"


def test_build_session_factory_uses_async_sessions() -> None:
    factory = build_session_factory("postgresql+asyncpg://postgres:postgres@localhost:5432/vkr_api")

    assert isinstance(factory, async_sessionmaker)
    assert factory.kw["expire_on_commit"] is False


@pytest.mark.asyncio
async def test_get_session_yields_async_session() -> None:
    factory = build_session_factory("postgresql+asyncpg://postgres:postgres@localhost:5432/vkr_api")

    session_generator = get_session(factory)
    session = await anext(session_generator)

    assert isinstance(session, AsyncSession)

    await session.close()
    with pytest.raises(StopAsyncIteration):
        await anext(session_generator)
