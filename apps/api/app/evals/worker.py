"""Evaluation worker entry point.

    python -m app.evals.worker <run_id>

Runs in its own process so re-pointing the application engine at per-scenario databases can never
disturb the API server. The process exits when the run reaches a terminal state.
"""

import asyncio
import sys
import uuid

from app.config import get_settings
from app.evals.runner import Runner
from app.evals.store import ResultsStore


async def execute(run_id: uuid.UUID, url: str | None = None) -> str:
    store = ResultsStore(url or get_settings().database_url)
    try:
        return await Runner(store, run_id).run()
    finally:
        await store.dispose()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.evals.worker <run_id>", file=sys.stderr)
        return 2
    try:
        run_id = uuid.UUID(argv[1])
    except ValueError:
        print("run id must be a UUID", file=sys.stderr)
        return 2
    status = asyncio.run(execute(run_id))
    print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
