"""Subprocess helper: asyncio, own process group, whole group killed on timeout/cancel."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class ProcessTimeoutError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def run_process(
    args: Sequence[str],
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> ProcessResult:
    """Run a command without blocking the event loop.

    The child gets its own session/process group so helpers it spawns (soffice.bin, ...) are
    killed together with it on timeout or cancellation. Raises FileNotFoundError when the
    command does not exist and ProcessTimeoutError on timeout.
    """
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=None if env is None else {**os.environ, **env},
        cwd=cwd,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError as exc:
        await _kill_group(process)
        raise ProcessTimeoutError(f"{Path(args[0]).name} timed out after {timeout:.0f}s") from exc
    except BaseException:
        await _kill_group(process)
        raise
    # Reap anything the command left behind in its group (e.g. a forked office daemon).
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    return ProcessResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace")[-2000:],
    )


async def _kill_group(process: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(process.wait(), 10)
