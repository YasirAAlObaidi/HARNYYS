"""The worker's loops: agent turns, outbox delivery, catalogue sync and recovery.

Each loop catches and logs its own errors and carries on, so one bad turn or a
down ERP never stops the others.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from yyai.core.config import WorkerConfig
from yyai.workflows.container import Workflows

logger = logging.getLogger(__name__)

ERROR_PAUSE_S = 2.0
SYNC_RETRY_S = 60.0
# How often recovery looks for dead turns. What counts as dead is `stale_after_s`; this is only how soon
# after that a crashed turn gets noticed, so it stays short however long `stale_after_s` is.
RECOVER_INTERVAL_S = 60.0
SHUTDOWN_GRACE_S = 20.0


async def run_worker(
    workflows: Workflows,
    worker_cfg: WorkerConfig,
    stop: asyncio.Event,
    *,
    grace_s: float = SHUTDOWN_GRACE_S,
) -> None:
    """Run until `stop` is set. Work in progress gets `grace_s` seconds to finish, then is cancelled."""
    try:
        recovered = await workflows.maintenance.recover()
        logger.info("Worker starting (recovered %s stale item(s))", recovered)
    except Exception:
        logger.exception("Recovery at startup failed; continuing")

    poll = worker_cfg.poll_interval_s
    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(
            _work_loop(f"turns-{n + 1}", workflows.turns.run_once, poll, stop), name=f"turns-{n + 1}"
        )
        for n in range(max(1, worker_cfg.turn_concurrency))
    ]
    tasks.append(
        asyncio.create_task(_work_loop("outbox", workflows.outbox.deliver_once, poll, stop), name="outbox")
    )
    tasks.append(
        asyncio.create_task(
            _periodic_loop(
                "catalogue-sync",
                workflows.catalogue_sync.run,
                interval_s=worker_cfg.catalogue_sync_interval_s,
                retry_s=min(worker_cfg.catalogue_sync_interval_s, SYNC_RETRY_S),
                run_first=True,
                stop=stop,
            ),
            name="catalogue-sync",
        )
    )
    tasks.append(
        asyncio.create_task(
            _periodic_loop(
                "recover",
                workflows.maintenance.recover,
                interval_s=min(worker_cfg.stale_after_s, RECOVER_INTERVAL_S),
                retry_s=ERROR_PAUSE_S,
                run_first=False,
                stop=stop,
            ),
            name="recover",
        )
    )

    await stop.wait()
    logger.info("Worker stopping; waiting up to %ss for work in progress", grace_s)
    _, pending = await asyncio.wait(tasks, timeout=grace_s)
    for task in pending:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Worker stopped")


async def _work_loop(
    name: str, step: Callable[[], Awaitable[bool]], idle_s: float, stop: asyncio.Event
) -> None:
    """Call `step` over and over. It returns True when it did something, so the next call is immediate."""
    while not stop.is_set():
        try:
            did_work = await step()
        except Exception:
            logger.exception("Loop %s failed; pausing and carrying on", name)
            await _sleep(stop, ERROR_PAUSE_S)
            continue
        if not did_work:
            await _sleep(stop, idle_s)


async def _periodic_loop(
    name: str,
    step: Callable[[], Awaitable[object]],
    *,
    interval_s: float,
    retry_s: float,
    run_first: bool,
    stop: asyncio.Event,
) -> None:
    """Call `step` every `interval_s`; after a failure try again after `retry_s`."""
    if not run_first:
        await _sleep(stop, interval_s)
    while not stop.is_set():
        try:
            await step()
        except Exception:
            logger.exception("Job %s failed; will try again in %ss", name, retry_s)
            await _sleep(stop, retry_s)
            continue
        await _sleep(stop, interval_s)


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    """Sleep, but wake at once when asked to stop."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(0.0, seconds))
    except TimeoutError:
        pass
