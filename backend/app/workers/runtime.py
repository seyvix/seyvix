from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import build_session_factory
from app.core.logging import configure_logging
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.content import models as content_models  # noqa: F401
from app.modules.snapshots import models as snapshot_models  # noqa: F401
from app.modules.tags import models as tags_models  # noqa: F401
from app.modules.taxonomy import models as taxonomy_models  # noqa: F401
from app.modules.vectorization import models as vectorization_models  # noqa: F401


@dataclass(frozen=True, slots=True)
class WorkerRuntime:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]


def build_worker_runtime() -> WorkerRuntime:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = build_session_factory(
        settings.sqlalchemy_database_uri,
        echo=settings.sqlalchemy_echo,
    )
    return WorkerRuntime(settings=settings, session_factory=session_factory)
