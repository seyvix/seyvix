from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.core.database import build_session_factory
from app.core.logging import configure_logging, get_logger
from app.modules.snapshots.worker import SnapshotWorker

logger = get_logger(__name__)


async def run_forever() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = build_session_factory(
        settings.sqlalchemy_database_uri,
        echo=settings.sqlalchemy_echo,
    )
    storage_root = Path(settings.content_storage_root)

    while True:
        async with session_factory() as session:
            processed = await SnapshotWorker(session, storage_root).run_once()
        if processed:
            logger.info("snapshot.worker.batch.done", processed=processed)
        await asyncio.sleep(settings.snapshot_worker_poll_interval_seconds)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
