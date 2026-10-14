"""With the Run Queue on, startup does not fail the runs waiting in it (#1310 1.5).

An admitted run is RUNNING with no container while it waits for a claim, so the
startup reconcile, which fails every pre-restart RUNNING execution once the
reap is done, would destroy it. With the flag on, expired claims are reconciled
by the ExecutionHost instead (ADR-072 D5); with it off, startup is main's.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from syn_api.services import execution_host_runner, lifecycle
from syn_api.services.reconciliation import CleanupResult

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@dataclass(frozen=True)
class _Execution:
    run_queue_enabled: bool


@dataclass(frozen=True)
class _Settings:
    execution: _Execution


async def _startup_reconciles(monkeypatch: pytest.MonkeyPatch, *, queue_on: bool) -> bool:
    reconcile = AsyncMock()
    monkeypatch.setattr(lifecycle, "reconcile_orphaned_sessions", AsyncMock())
    monkeypatch.setattr(
        lifecycle,
        "cleanup_orphaned_containers",
        AsyncMock(return_value=CleanupResult(fully_reaped=True, failures=())),
    )
    monkeypatch.setattr(execution_host_runner, "reconcile_orphaned_executions", reconcile)
    monkeypatch.setattr(lifecycle, "_SERVICE_REGISTRY", ())
    monkeypatch.setattr(
        execution_host_runner,
        "get_settings",
        lambda: _Settings(_Execution(run_queue_enabled=queue_on)),
    )
    await lifecycle._init_degradable_services(lifecycle.LifecycleState())
    return reconcile.await_count == 1


async def test_flag_on_leaves_admitted_runs_to_the_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not await _startup_reconciles(monkeypatch, queue_on=True)


async def test_flag_off_reconciles_as_main_does(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await _startup_reconciles(monkeypatch, queue_on=False)
