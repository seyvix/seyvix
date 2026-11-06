"""Run background modules.

python -m app.worker all
python -m app.worker snapshots
python -m app.worker vectorization tags taxonomy maintenance
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib

from app.core.config import get_settings
from app.core.database import build_engine, build_session_factory_from_engine
from app.core.logging import configure_logging, get_logger
from app.models import import_all_models
from app.modules.llm.client import close_ai_client
from app.platform.heartbeat import HeartbeatWriter
from app.platform.jobs import default_worker_id
from app.platform.storage.factory import build_storage_backend
from app.worker.context import WorkerContext
from app.worker.modules import MODULES
from app.worker.supervisor import Supervisor


def parse_modules(argv: list[str] | None = None) -> list[str]:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument(
        "modules",
        nargs="+",
        choices=[*MODULES, "all"],
        help="modules to run in this process",
    )
    selected: list[str] = parser.parse_args(argv).modules
    return list(MODULES) if "all" in selected else list(dict.fromkeys(selected))


async def run(modules: list[str]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    import_all_models()
    engine = build_engine(settings, application_name=f"worker:{','.join(modules)}")
    ctx = WorkerContext(
        settings=settings,
        session_factory=build_session_factory_from_engine(engine),
        storage=build_storage_backend(settings),
        worker_id=default_worker_id("+".join(modules)),
    )
    loops = [loop for name in modules for loop in MODULES[name](ctx)]
    listen_dsn = settings.sqlalchemy_database_uri.replace("postgresql+asyncpg://", "postgresql://")
    heartbeat = HeartbeatWriter(
        ctx.session_factory,
        worker_id=ctx.worker_id,
        modules=modules,
        version=settings.app_version,
    )
    try:
        await Supervisor(loops, listen_dsn=listen_dsn, heartbeat=heartbeat.beat).run()
    finally:
        with contextlib.suppress(Exception):
            await heartbeat.remove()
        await close_ai_client()
        await engine.dispose()
        get_logger(__name__).info("worker.exit", modules=modules)


def main() -> None:
    asyncio.run(run(parse_modules()))


if __name__ == "__main__":
    main()
