from collections.abc import AsyncIterator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_engine(settings: Settings, *, application_name: str) -> AsyncEngine:
    """Create the process-wide engine with bounded pool and server-side timeouts.

    Every process (api, worker) owns exactly one engine; the pool is sized so that
    api + worker stay far below Postgres `max_connections`.
    """
    server_settings = {"application_name": application_name}
    if settings.db_statement_timeout_ms:
        server_settings["statement_timeout"] = str(settings.db_statement_timeout_ms)
    return create_async_engine(
        settings.sqlalchemy_database_uri,
        echo=settings.sqlalchemy_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"server_settings": server_settings},
    )


def build_session_factory_from_engine(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def build_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Small helper for tests and scripts that only have a URL."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return build_session_factory_from_engine(engine)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
