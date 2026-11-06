"""Shared primitives for Postgres-backed job tables.

Every module job table mixes in `JobColumnsMixin` and processes rows with `JobQueue`:

1. `claim()` in a short transaction (SKIP LOCKED + lease), then COMMIT immediately;
2. do the slow work (network, browser, AI) without holding row locks;
3. finalize each job in its own short transaction via `succeed()` / `fail()`.

A job whose lease expires (worker crashed mid-job) becomes claimable again, and failures
retry with exponential backoff until `max_attempts`, after which the job is `failed`.
"""

from __future__ import annotations

import socket
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Final
from uuid import uuid4

from sqlalchemy import (
    DDL,
    ColumnElement,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    event,
    or_,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

JOB_PENDING: Final = "pending"
JOB_PROCESSING: Final = "processing"
JOB_SUCCEEDED: Final = "succeeded"
JOB_FAILED: Final = "failed"
JOB_CANCELLED: Final = "cancelled"
JOB_ACTIVE_STATUSES: Final = (JOB_PENDING, JOB_PROCESSING)

# Workers LISTEN on this channel; payload is the job table name.
NOTIFY_CHANNEL: Final = "seyvix_jobs"
NOTIFY_FUNCTION_SQL: Final = f"""
CREATE OR REPLACE FUNCTION seyvix_notify_job() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = '{JOB_PENDING}' THEN
        PERFORM pg_notify('{NOTIFY_CHANNEL}', TG_TABLE_NAME);
    END IF;
    RETURN NULL;
END
$$;
"""


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobColumnsMixin:
    """Columns required by `JobQueue`. Status values are the JOB_* constants above."""

    status: Mapped[str] = mapped_column(String(16), default=JOB_PENDING)
    priority: Mapped[int] = mapped_column(Integer(), default=100)
    attempts: Mapped[int] = mapped_column(Integer(), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer(), default=5)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


def job_queue_indexes(table_name: str) -> tuple[Index, ...]:
    """Partial indexes that keep `claim()` an index-only lookup regardless of history size.

    Use inside the model: `__table_args__ = (*job_queue_indexes("x_jobs"), ...)`.
    """
    return (
        Index(
            f"ix_{table_name}_claim",
            text("priority DESC"),
            "run_after",
            postgresql_where=text(f"status = '{JOB_PENDING}'"),
        ),
        Index(
            f"ix_{table_name}_lease",
            "locked_at",
            postgresql_where=text(f"status = '{JOB_PROCESSING}'"),
        ),
    )


def notify_trigger_sql(table_name: str) -> str:
    return (
        f"CREATE TRIGGER {table_name}_notify AFTER INSERT OR UPDATE OF status, run_after "
        f"ON {table_name} FOR EACH ROW EXECUTE FUNCTION seyvix_notify_job();"
    )


def is_job_table(table: Table) -> bool:
    return all(name in table.c for name in ("status", "run_after", "locked_by"))


def job_table_names(metadata: MetaData) -> list[str]:
    return sorted(name for name, table in metadata.tables.items() if is_job_table(table))


def register_notify_triggers(metadata: MetaData) -> None:
    """Attach NOTIFY triggers to every job table on `create_all` (tests, fresh installs).
    The alembic baseline creates the same triggers via `notify_trigger_sql`."""
    for table in metadata.tables.values():
        if not is_job_table(table) or table.info.get("notify_trigger_registered"):
            continue
        table.info["notify_trigger_registered"] = True
        event.listen(table, "after_create", DDL(NOTIFY_FUNCTION_SQL))  # type: ignore[no-untyped-call]
        event.listen(table, "after_create", DDL(notify_trigger_sql(table.name)))  # type: ignore[no-untyped-call]


def default_worker_id(prefix: str) -> str:
    return f"{prefix}@{socket.gethostname()}:{uuid4().hex[:8]}"


class JobQueue[JobT: JobColumnsMixin]:
    backoff_base_seconds: ClassVar[int] = 30
    backoff_max_seconds: ClassVar[int] = 6 * 3600

    def __init__(self, model: type[JobT], *, lease_seconds: int, worker_id: str) -> None:
        self.model = model
        self.lease_seconds = lease_seconds
        self.worker_id = worker_id

    async def claim(
        self,
        session: AsyncSession,
        *,
        limit: int,
        filters: Sequence[ColumnElement[bool]] = (),
    ) -> list[JobT]:
        """Claim due jobs. The caller MUST commit right after this returns."""
        now = utcnow()
        model: Any = self.model
        stale_before = now - timedelta(seconds=self.lease_seconds)
        query = (
            select(self.model)
            .where(
                or_(
                    (model.status == JOB_PENDING) & (model.run_after <= now),
                    (model.status == JOB_PROCESSING) & (model.locked_at < stale_before),
                ),
                *filters,
            )
            .order_by(model.priority.desc(), model.run_after.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        jobs = list(await session.scalars(query))
        for job in jobs:
            job.status = JOB_PROCESSING
            job.attempts += 1
            job.locked_at = now
            job.locked_by = self.worker_id
        await session.flush()
        return jobs

    @staticmethod
    def succeed(job: JobColumnsMixin) -> None:
        job.status = JOB_SUCCEEDED
        job.last_error = None
        job.locked_at = None
        job.locked_by = None

    @classmethod
    def fail(cls, job: JobColumnsMixin, error: str, *, retryable: bool = True) -> None:
        job.last_error = error[:4000]
        job.locked_at = None
        job.locked_by = None
        if retryable and job.attempts < job.max_attempts:
            delay = min(
                cls.backoff_base_seconds * 2 ** max(job.attempts - 1, 0), cls.backoff_max_seconds
            )
            job.status = JOB_PENDING
            job.run_after = utcnow() + timedelta(seconds=delay)
            return
        job.status = JOB_FAILED

    @staticmethod
    def reset(job: JobColumnsMixin, *, priority: int | None = None) -> None:
        """Re-queue a job (e.g. content changed or user requested reprocessing)."""
        job.status = JOB_PENDING
        job.attempts = 0
        job.run_after = utcnow()
        job.locked_at = None
        job.locked_by = None
        job.last_error = None
        if priority is not None:
            job.priority = priority
