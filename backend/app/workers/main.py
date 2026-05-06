from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Coroutine
from typing import Any, Final

from app.workers.run.tags import run_tags_worker
from app.workers.run.taxonomy import run_taxonomy_worker
from app.workers.run.vectorization import run_vectorization_worker

WORKER_MODES: Final[dict[str, Callable[[], Coroutine[Any, Any, None]]]] = {
    "tags-worker": run_tags_worker,
    "taxonomy-worker": run_taxonomy_worker,
    "vectorization-worker": run_vectorization_worker,
}


def main() -> None:
    if len(sys.argv) != 2:
        modes = "|".join(WORKER_MODES)
        raise SystemExit(f"Usage: python -m app.workers.main <{modes}>")

    mode = sys.argv[1]
    try:
        worker_runner = WORKER_MODES[mode]
    except KeyError as exc:
        raise SystemExit(f"Unknown worker mode: {mode}") from exc

    asyncio.run(worker_runner())


if __name__ == "__main__":
    main()
