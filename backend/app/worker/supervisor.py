from __future__ import annotations

import asyncio
import contextlib
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg

from app.core.logging import get_logger
from app.platform.jobs import NOTIFY_CHANNEL

logger = get_logger(__name__)

HEARTBEAT_PATH = Path("/tmp/seyvix-worker.heartbeat")


def _touch_heartbeat_file() -> None:
    """Container healthcheck reads the mtime/content of this file."""
    HEARTBEAT_PATH.write_text(str(int(time.time())))


def _clear_heartbeat_file() -> None:
    HEARTBEAT_PATH.unlink(missing_ok=True)


@dataclass(slots=True)
class Loop:
    """A supervised polling loop woken early by NOTIFY on any of `tables`."""

    name: str
    run_once: Callable[[], Awaitable[int]]
    tables: tuple[str, ...] = ()
    idle_seconds: float = 10.0
    close: Callable[[], Awaitable[None]] | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    processed_total: int = 0
    failures_total: int = 0
    last_run_at: float | None = None
    last_error: str | None = None
    last_error_at: float | None = None

    def stats(self) -> dict[str, object]:
        return {
            "processed_total": self.processed_total,
            "failures_total": self.failures_total,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
        }


class Supervisor:
    def __init__(
        self,
        loops: list[Loop],
        *,
        listen_dsn: str | None,
        stop_grace_seconds: float = 25.0,
        heartbeat: Callable[[dict[str, object]], Awaitable[None]] | None = None,
        heartbeat_interval_seconds: float = 15.0,
    ) -> None:
        self.loops = loops
        self.listen_dsn = listen_dsn
        self.stop_grace_seconds = stop_grace_seconds
        self.heartbeat = heartbeat
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.stopping = asyncio.Event()
        self._by_table: dict[str, list[Loop]] = {}
        for loop in loops:
            for table in loop.tables:
                self._by_table.setdefault(table, []).append(loop)

    # --- lifecycle -----------------------------------------------------------------------
    async def run(self) -> None:
        running = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                running.add_signal_handler(sig, self.stop)

        logger.info("worker.started", loops=[loop.name for loop in self.loops])
        tasks = [asyncio.create_task(self._run_loop(loop), name=loop.name) for loop in self.loops]
        aux = [asyncio.create_task(self._heartbeat(), name="heartbeat")]
        if self.listen_dsn:
            aux.append(asyncio.create_task(self._listen(self.listen_dsn), name="listener"))

        await self.stopping.wait()
        logger.info("worker.stopping")
        _, pending = await asyncio.wait(tasks, timeout=self.stop_grace_seconds)
        for task in [*pending, *aux]:
            task.cancel()
        await asyncio.gather(*pending, *aux, return_exceptions=True)
        for loop in self.loops:
            if loop.close is not None:
                with contextlib.suppress(Exception):
                    await loop.close()
        _clear_heartbeat_file()
        logger.info("worker.stopped")

    def stop(self) -> None:
        self.stopping.set()
        for loop in self.loops:
            loop.wake.set()

    # --- loops ---------------------------------------------------------------------------
    async def _run_loop(self, loop: Loop) -> None:
        failures = 0
        while not self.stopping.is_set():
            loop.wake.clear()
            try:
                processed = await loop.run_once()
                failures = 0
                loop.processed_total += processed
                loop.last_run_at = time.time()
            except Exception as exc:  # noqa: BLE001 - a loop must never die
                failures += 1
                loop.failures_total += 1
                loop.last_error = f"{type(exc).__name__}: {exc}"[:500]
                loop.last_error_at = time.time()
                delay = min(2**failures, 60)
                logger.error(
                    "worker.loop.error",
                    loop=loop.name,
                    error=str(exc),
                    retry_in_seconds=delay,
                    exc_info=True,
                )
                await self._sleep(loop, delay)
                continue
            if processed == 0:
                await self._sleep(loop, loop.idle_seconds)

    async def _sleep(self, loop: Loop, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(loop.wake.wait(), timeout=seconds)

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        for loop in self._by_table.get(payload, ()):
            loop.wake.set()

    async def _listen(self, dsn: str) -> None:
        failures = 0
        while not self.stopping.is_set():
            conn: asyncpg.Connection | None = None
            try:
                conn = await asyncpg.connect(
                    dsn, server_settings={"application_name": "worker-listen"}
                )
                await conn.add_listener(NOTIFY_CHANNEL, self._on_notify)
                failures = 0
                logger.info("worker.listener.connected")
                # Wake everyone once: we may have missed notifications while disconnected.
                for loop in self.loops:
                    loop.wake.set()
                while not self.stopping.is_set() and not conn.is_closed():
                    await asyncio.sleep(15)
                    await conn.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - fall back to polling meanwhile
                failures += 1
                logger.warning("worker.listener.error", error=str(exc))
                await asyncio.sleep(min(2**failures, 30))
            finally:
                if conn is not None and not conn.is_closed():
                    with contextlib.suppress(Exception):
                        await conn.close()

    async def _heartbeat(self) -> None:
        while True:
            _touch_heartbeat_file()
            if self.heartbeat is not None:
                try:
                    await self.heartbeat({loop.name: loop.stats() for loop in self.loops})
                except Exception as exc:  # noqa: BLE001 - DB hiccups must not stop the worker
                    logger.warning("worker.heartbeat.error", error=str(exc))
            await asyncio.sleep(self.heartbeat_interval_seconds)
