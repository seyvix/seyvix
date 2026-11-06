from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_session


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory(request)
    async for session in get_session(session_factory):
        yield session
