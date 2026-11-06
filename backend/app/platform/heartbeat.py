"""Worker liveness registry, shown in the admin panel."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, Integer, String, delete
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.platform.jobs import utcnow


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    modules: Mapped[str] = mapped_column(String(255))
    hostname: Mapped[str] = mapped_column(String(255))
    pid: Mapped[int] = mapped_column(Integer())
    version: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    loops: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict)


class HeartbeatWriter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        worker_id: str,
        modules: list[str],
        version: str,
    ) -> None:
        self.session_factory = session_factory
        self.values: dict[str, Any] = {
            "worker_id": worker_id,
            "modules": ",".join(modules),
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "version": version,
            "started_at": utcnow(),
        }

    async def beat(self, loops: dict[str, Any]) -> None:
        now = utcnow()
        statement = insert(WorkerHeartbeat).values(**self.values, last_seen_at=now, loops=loops)
        statement = statement.on_conflict_do_update(
            index_elements=[WorkerHeartbeat.worker_id],
            set_={"last_seen_at": now, "loops": loops},
        )
        async with self.session_factory() as session:
            await session.execute(statement)
            await session.commit()

    async def remove(self) -> None:
        async with self.session_factory() as session:
            await session.execute(
                delete(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == self.values["worker_id"])
            )
            await session.commit()


async def prune_heartbeats(session: AsyncSession, *, older_than: timedelta) -> None:
    await session.execute(
        delete(WorkerHeartbeat).where(WorkerHeartbeat.last_seen_at < utcnow() - older_than)
    )
