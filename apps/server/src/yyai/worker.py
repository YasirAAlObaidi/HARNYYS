"""The worker process: `python -m yyai.worker`.

Runs agent turns, delivers the outbox, syncs the catalogue and recovers work cut
off by a crash. SIGINT and SIGTERM ask it to stop; work in progress gets a short
grace period to finish.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from yyai.bootstrap import build
from yyai.core.config import load_config
from yyai.core.logging import configure_logging
from yyai.entry.jobs.runner import run_worker

logger = logging.getLogger(__name__)


async def _main() -> None:
    configure_logging()
    config = load_config()
    workflows = build(config)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        await run_worker(workflows, config.worker, stop)
    finally:
        await workflows.aclose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
