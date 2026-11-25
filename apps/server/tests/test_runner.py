"""The worker's loops, with fake workflows and no database."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from yyai.core.config import WorkerConfig
from yyai.entry.jobs import runner


class Counter:
    def __init__(self, result: object = False) -> None:
        self.calls = 0
        self._result = result

    async def __call__(self) -> object:
        self.calls += 1
        return self._result


def fake_workflows() -> SimpleNamespace:
    return SimpleNamespace(
        turns=SimpleNamespace(run_once=Counter(False)),
        outbox=SimpleNamespace(deliver_once=Counter(False)),
        catalogue_sync=SimpleNamespace(run=Counter(0)),
        maintenance=SimpleNamespace(recover=Counter(0)),
    )


async def run_for(workflows: SimpleNamespace, config: WorkerConfig, seconds: float) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(runner.run_worker(workflows, config, stop, grace_s=1.0))  # type: ignore[arg-type]
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, timeout=5)


async def test_recovery_looks_for_dead_turns_often_even_with_a_long_stale_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # stale_after_s decides what counts as dead; it must not also set how rarely we look, or a crashed
    # turn would sit unanswered for up to twice that long.
    monkeypatch.setattr(runner, "RECOVER_INTERVAL_S", 0.05)
    workflows = fake_workflows()

    await run_for(workflows, WorkerConfig(poll_interval_s=0.01, stale_after_s=900), 0.4)

    assert workflows.maintenance.recover.calls >= 4  # once at startup, then every interval


async def test_recovery_interval_never_exceeds_a_short_stale_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "RECOVER_INTERVAL_S", 60.0)
    workflows = fake_workflows()

    await run_for(workflows, WorkerConfig(poll_interval_s=0.01, stale_after_s=0.05), 0.4)

    assert workflows.maintenance.recover.calls >= 4


async def test_idle_loops_poll_and_the_catalogue_syncs_at_startup() -> None:
    workflows = fake_workflows()

    await run_for(workflows, WorkerConfig(poll_interval_s=0.02, catalogue_sync_interval_s=3600), 0.2)

    assert workflows.turns.run_once.calls >= 3
    assert workflows.outbox.deliver_once.calls >= 3
    assert workflows.catalogue_sync.run.calls == 1


async def test_a_failing_loop_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "ERROR_PAUSE_S", 0.02)
    workflows = fake_workflows()

    async def explode() -> bool:
        raise RuntimeError("model server on fire")

    workflows.turns.run_once = explode  # type: ignore[assignment]

    await run_for(workflows, WorkerConfig(poll_interval_s=0.02), 0.2)

    assert workflows.outbox.deliver_once.calls >= 3
    assert workflows.catalogue_sync.run.calls == 1
