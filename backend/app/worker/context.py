from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.platform.storage.service import StorageBackend


@dataclass(frozen=True, slots=True)
class WorkerContext:
    """Process-wide dependencies handed to every module handler and job runner."""

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    storage: StorageBackend
    worker_id: str


class JobRunner(Protocol):
    """A module's job processor (one per module and process).

    `run_once` claims and processes at most one batch and returns how many jobs it touched
    (0 means idle). It must never hold row locks during slow work: claim + commit, work,
    then finalize each job in a short transaction (see `app.platform.jobs`). Unexpected
    exceptions are caught by the supervisor, logged and retried with backoff.
    `aclose` releases long-lived resources (browser, HTTP clients) on shutdown.
    """

    async def run_once(self) -> int: ...

    async def aclose(self) -> None: ...
