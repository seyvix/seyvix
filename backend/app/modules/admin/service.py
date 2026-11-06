"""Read-mostly operational insight for the owner: host, database, storage, queues, workers.

Queues are discovered from ORM metadata (every table with job columns, plus per-consumer
event queues), so new modules show up here automatically.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Table, and_, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import Settings
from app.core.database import Base
from app.platform.events.models import EventDelivery
from app.platform.heartbeat import WorkerHeartbeat
from app.platform.jobs import (
    JOB_FAILED,
    JOB_PENDING,
    JOB_PROCESSING,
    JOB_SUCCEEDED,
    job_table_names,
    utcnow,
)

PROCESS_STARTED_AT = time.time()
WORKER_STALE_AFTER = timedelta(seconds=60)
EVENT_QUEUE_PREFIX = "events:"
JOB_SUMMARY_COLUMNS = (
    "job_type",
    "content_object_id",
    "source_asset_id",
    "owner_user_id",
    "source",
    "source_id",
    "consumer",
    "event_id",
)


@dataclass(slots=True)
class _StorageUsageCache:
    computed_at: float = 0.0
    value: dict[str, Any] | None = None


_storage_cache = _StorageUsageCache()
_storage_lock = asyncio.Lock()


def _read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) * 1024
    except OSError:
        return {}
    return values


def _read_cgroup_memory() -> dict[str, int | None]:
    def read(path: str) -> int | None:
        try:
            raw = Path(path).read_text().strip()
        except OSError:
            return None
        return int(raw) if raw.isdigit() else None

    return {
        "current_bytes": read("/sys/fs/cgroup/memory.current"),
        "limit_bytes": read("/sys/fs/cgroup/memory.max"),
    }


def host_metrics(storage_root: Path | None) -> dict[str, Any]:
    meminfo = _read_meminfo()
    disk_path = storage_root if storage_root and storage_root.exists() else Path("/")
    disk = shutil.disk_usage(disk_path)
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    return {
        "cpu_count": os.cpu_count(),
        "load_average": [round(value, 2) for value in load],
        "memory_total_bytes": meminfo.get("MemTotal"),
        "memory_available_bytes": meminfo.get("MemAvailable"),
        "api_container_memory": _read_cgroup_memory(),
        "disk_path": str(disk_path),
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "api_uptime_seconds": int(time.time() - PROCESS_STARTED_AT),
    }


def _directory_usage(root: Path) -> dict[str, Any]:
    total = 0
    files = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
            files += 1
    return {"used_bytes": total, "files": files}


async def storage_usage(storage: Any, *, force: bool = False) -> dict[str, Any]:
    """Local backend only (walks the volume in a thread, cached for 10 minutes)."""
    root: Path | None = getattr(storage, "root", None)
    if root is None:
        return {"backend": type(storage).__name__, "used_bytes": None, "files": None}
    async with _storage_lock:
        fresh = time.time() - _storage_cache.computed_at < 600
        if _storage_cache.value is None or force or not fresh:
            usage = await asyncio.to_thread(_directory_usage, Path(root))
            _storage_cache.value = {"backend": "local", "root": str(root), **usage}
            _storage_cache.computed_at = time.time()
        return {**_storage_cache.value, "computed_at": _storage_cache.computed_at}


def _job_table(name: str) -> Table:
    if name not in job_table_names(Base.metadata):
        raise AppError(status_code=404, code="queue_not_found", message=f"Unknown queue {name}")
    return Base.metadata.tables[name]


def _queue_target(queue: str) -> tuple[Table, list[Any]]:
    """Resolve a queue id (`<job_table>` or `events:<consumer>`) to table + row filter."""
    if queue.startswith(EVENT_QUEUE_PREFIX):
        consumer = queue.removeprefix(EVENT_QUEUE_PREFIX)
        table = EventDelivery.__table__
        assert isinstance(table, Table)
        return table, [table.c.consumer == consumer]
    return _job_table(queue), []


class AdminService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def database(self) -> dict[str, Any]:
        size = await self.session.scalar(text("SELECT pg_database_size(current_database())"))
        connections = await self.session.execute(
            text(
                "SELECT coalesce(application_name, '') AS app, count(*) AS n "
                "FROM pg_stat_activity WHERE datname = current_database() "
                "GROUP BY 1 ORDER BY 2 DESC"
            )
        )
        tables = await self.session.execute(
            text(
                "SELECT c.relname AS name, pg_total_relation_size(c.oid) AS total_bytes, "
                "greatest(c.reltuples, 0)::bigint AS rows_estimate "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                "ORDER BY total_bytes DESC LIMIT 15"
            )
        )
        version = await self.session.scalar(text("SHOW server_version"))
        return {
            "version": version,
            "size_bytes": int(size or 0),
            "connections": [{"application": row.app, "count": row.n} for row in connections],
            "tables": [
                {"name": row.name, "total_bytes": row.total_bytes, "rows": row.rows_estimate}
                for row in tables
            ],
        }

    async def _queue_stats(self, queue: str, table: Table, filters: list[Any]) -> dict[str, Any]:
        now = utcnow()
        status_rows = await self.session.execute(
            select(table.c.status, func.count()).where(*filters).group_by(table.c.status)
        )
        counts: dict[str, int] = {str(row[0]): int(row[1]) for row in status_rows}
        oldest_pending = await self.session.scalar(
            select(func.min(table.c.run_after)).where(
                *filters, table.c.status == JOB_PENDING, table.c.run_after <= now
            )
        )
        succeeded_24h = await self.session.scalar(
            select(func.count()).where(
                *filters,
                table.c.status == JOB_SUCCEEDED,
                table.c.updated_at >= now - timedelta(hours=24),
            )
        )
        return {
            "queue": queue,
            "kind": "events" if queue.startswith(EVENT_QUEUE_PREFIX) else "jobs",
            "pending": int(counts.get(JOB_PENDING, 0)),
            "processing": int(counts.get(JOB_PROCESSING, 0)),
            "failed": int(counts.get(JOB_FAILED, 0)),
            "succeeded_24h": int(succeeded_24h or 0),
            "oldest_pending_seconds": (
                int((now - oldest_pending).total_seconds()) if oldest_pending else None
            ),
        }

    async def queues(self) -> list[dict[str, Any]]:
        consumers = await self.session.scalars(select(EventDelivery.consumer).distinct())
        names = [f"{EVENT_QUEUE_PREFIX}{c}" for c in sorted(consumers)]
        names += job_table_names(Base.metadata)
        result = []
        for name in names:
            if name == EventDelivery.__tablename__:
                continue
            table, filters = _queue_target(name)
            result.append(await self._queue_stats(name, table, filters))
        return result

    async def workers(self) -> list[dict[str, Any]]:
        rows = await self.session.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.modules))
        now = utcnow()
        return [
            {
                "worker_id": row.worker_id,
                "modules": row.modules.split(","),
                "hostname": row.hostname,
                "pid": row.pid,
                "version": row.version,
                "started_at": row.started_at,
                "last_seen_at": row.last_seen_at,
                "alive": now - row.last_seen_at < WORKER_STALE_AFTER,
                "loops": row.loops,
            }
            for row in rows
        ]

    async def _count(self, table_name: str, *conditions: str) -> int | None:
        if table_name not in Base.metadata.tables:
            return None
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        value = await self.session.scalar(text(f"SELECT count(*) FROM {table_name}{where}"))
        return int(value or 0)

    async def totals(self) -> dict[str, Any]:
        return {
            "users": await self._count("users"),
            "active_sessions": await self._count(
                "auth_sessions", "revoked_at IS NULL", "expires_at > now()"
            ),
            "notes": await self._count("content_objects", "deleted_at IS NULL"),
            "notes_last_24h": await self._count(
                "content_objects", "deleted_at IS NULL", "created_at > now() - interval '1 day'"
            ),
            "notes_in_trash": await self._count("content_objects", "deleted_at IS NOT NULL"),
            "assets": await self._count("content_assets"),
        }

    def config_summary(self) -> dict[str, Any]:
        s = self.settings
        return {
            "version": s.app_version,
            "environment": s.app_env,
            "public_url": s.public_origin,
            "access_mode": s.access_mode,
            "admins": s.admin_telegram_ids,
            "storage_backend": s.storage_backend,
            "ai_enabled": s.ai_enabled,
            "ai_base_url": s.ai_base_url if s.ai_enabled else None,
            "ai_models": {
                "chat": s.ai_chat_model,
                "embedding": s.ai_embedding_model,
                "embedding_dimensions": s.ai_embedding_dimensions,
                "vision": s.ai_vision_model,
                "transcription": s.ai_transcription_model,
            },
            "ai_features": {
                "tags": s.ai_tags_enabled,
                "taxonomy": s.ai_taxonomy_enabled,
                "ocr": s.ai_ocr_enabled,
                "vision": s.ai_vision_enabled,
                "transcription": s.ai_transcription_enabled,
                "query_expansion": s.ai_query_expansion_enabled,
            },
            "snapshots": {
                "screenshot": s.snapshot_screenshot_enabled,
                "page_pdf": s.snapshot_page_pdf_enabled,
                "webpage_html": s.snapshot_webpage_html_enabled,
                "office_conversion": s.snapshot_office_conversion_enabled,
            },
            "telegram_bot_configured": bool(s.telegram_bot_token),
        }

    async def list_jobs(
        self, queue: str, *, status: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        table, filters = _queue_target(queue)
        if status:
            filters = [*filters, table.c.status == status]
        columns = [
            table.c.id,
            table.c.status,
            table.c.attempts,
            table.c.max_attempts,
            table.c.priority,
            table.c.run_after,
            table.c.locked_by,
            table.c.last_error,
            table.c.created_at,
            table.c.updated_at,
            *(table.c[name] for name in JOB_SUMMARY_COLUMNS if name in table.c),
        ]
        total = await self.session.scalar(select(func.count()).select_from(table).where(*filters))
        rows = await self.session.execute(
            select(*columns)
            .where(*filters)
            .order_by(table.c.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return {"queue": queue, "total": int(total or 0), "items": [dict(r._mapping) for r in rows]}

    async def retry_jobs(self, queue: str, *, ids: list[str] | None) -> int:
        """Re-queue failed jobs (all failed ones when `ids` is None)."""
        table, filters = _queue_target(queue)
        conditions = [*filters, table.c.status == JOB_FAILED]
        if ids is not None:
            conditions.append(table.c.id.in_(ids))
        result = await self.session.execute(
            update(table)
            .where(and_(*conditions))
            .values(
                status=JOB_PENDING,
                attempts=0,
                run_after=utcnow(),
                locked_at=None,
                locked_by=None,
                last_error=None,
                updated_at=utcnow(),
            )
        )
        await self.session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    async def purge_failed(self, queue: str) -> int:
        table, filters = _queue_target(queue)
        result = await self.session.execute(
            delete(table).where(*filters, table.c.status == JOB_FAILED)
        )
        await self.session.commit()
        return int(getattr(result, "rowcount", 0) or 0)
