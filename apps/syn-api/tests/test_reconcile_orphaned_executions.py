"""Startup reconciliation of executions stranded by a restart (#1120).

The defect this guards: `cleanup_orphaned_containers` reaps every workspace
container on startup, and nothing then told the domain. Nine executions sat in
'running' for six hours after a deploy, and cancel returned 200 without acting,
because the processor that would act was gone.

The assertions that matter are (a) the correction goes through the AGGREGATE, so
it lands in the event stream rather than only in a read model a replay would
overwrite, and (b) one bad row cannot abort the sweep - a restart that gives up
halfway is a restart that leaves zombies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

from syn_api.services.reconciliation import CleanupResult, reconcile_orphaned_executions

_REAPED = CleanupResult(fully_reaped=True)
#: Every execution in these fixtures started before this, so the cutoff never
#: silently does the work an assertion is claiming.
_CUTOFF = datetime(2030, 1, 1, tzinfo=UTC)


@dataclass
class _Summary:
    workflow_execution_id: str
    completed_phases: int = 1
    total_phases: int = 3
    started_at: datetime = datetime(2026, 9, 3, 3, 15, tzinfo=UTC)


class _StubExecutionList:
    def __init__(self, rows: Sequence[_Summary]) -> None:
        self._rows = list(rows)
        self.status_filter_seen: str | None = None

    async def get_all(
        self, limit: int = 100, offset: int = 0, status_filter: str | None = None
    ) -> list[_Summary]:
        self.status_filter_seen = status_filter
        return self._rows[offset : offset + limit]


class _StubManager:
    def __init__(self, rows: Sequence[_Summary]) -> None:
        self.workflow_execution_list = _StubExecutionList(rows)


class _StubAggregate:
    def __init__(
        self, execution_id: str, *, raises: bool = False, running_phase_id: str | None = "verify"
    ) -> None:
        self.execution_id = execution_id
        self._raises = raises
        self.running_phase_id = running_phase_id
        self.failed_with: object | None = None

    def fail_execution(self, command: object) -> None:
        if self._raises:
            msg = "Cannot fail execution in status completed"
            raise ValueError(msg)
        self.failed_with = command


class _StubRepository:
    def __init__(self, aggregates: dict[str, _StubAggregate | None]) -> None:
        self._aggregates = aggregates
        self.saved: list[str] = []

    async def get_by_id(self, aggregate_id: str) -> _StubAggregate | None:
        return self._aggregates.get(aggregate_id)

    async def save(self, aggregate: _StubAggregate) -> None:
        self.saved.append(aggregate.execution_id)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    rows: Sequence[_Summary],
    aggregates: dict[str, _StubAggregate | None],
) -> tuple[_StubManager, _StubRepository]:
    manager = _StubManager(rows)
    repository = _StubRepository(aggregates)
    monkeypatch.setattr("syn_api._wiring.get_projection_mgr", lambda: manager)
    monkeypatch.setattr(
        "syn_adapters.storage.repositories.get_workflow_execution_repository",
        lambda: repository,
    )
    return manager, repository


@pytest.mark.unit
@pytest.mark.anyio
async def test_stranded_executions_are_failed_through_the_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a projection write: the aggregate is commanded and saved."""
    agg = _StubAggregate("exec-1")
    manager, repository = _install(monkeypatch, [_Summary("exec-1")], {"exec-1": agg})

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert repository.saved == ["exec-1"]
    assert agg.failed_with is not None
    assert manager.workflow_execution_list.status_filter_seen == "running"


@pytest.mark.unit
@pytest.mark.anyio
async def test_the_reason_says_a_restart_did_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator reading the failed run must learn why without a code search."""
    agg = _StubAggregate("exec-1")
    _install(monkeypatch, [_Summary("exec-1")], {"exec-1": agg})

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    command = agg.failed_with
    assert command is not None
    assert "restarted" in getattr(command, "error", "")
    assert getattr(command, "error_type", None) == "OrphanedByRestart"


@pytest.mark.unit
@pytest.mark.anyio
async def test_one_bad_row_does_not_abort_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """A row the aggregate rejects must not strand the rows behind it.

    `exec-2` is a projection row lagging behind a terminal aggregate - the
    aggregate raises, which is the correct guard - and `exec-3` must still be
    reconciled.
    """
    good_first = _StubAggregate("exec-1")
    good_last = _StubAggregate("exec-3")
    _, repository = _install(
        monkeypatch,
        [_Summary("exec-1"), _Summary("exec-2"), _Summary("exec-3")],
        {
            "exec-1": good_first,
            "exec-2": _StubAggregate("exec-2", raises=True),
            "exec-3": good_last,
        },
    )

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert repository.saved == ["exec-1", "exec-3"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_row_with_no_aggregate_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing is invented for a read-model row with no event stream behind it."""
    _, repository = _install(monkeypatch, [_Summary("exec-ghost")], {"exec-ghost": None})

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert repository.saved == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_nothing_stranded_touches_no_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    _, repository = _install(monkeypatch, [], {})

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert repository.saved == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_nothing_is_failed_when_the_reap_could_not_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unverified reap cannot license declaring other people's work dead.

    Docker unreachable used to be a DEBUG line, after which every running
    execution was failed on the strength of a reap that may have removed
    nothing.
    """
    agg = _StubAggregate("exec-1")
    _, repository = _install(monkeypatch, [_Summary("exec-1")], {"exec-1": agg})

    await reconcile_orphaned_executions(
        CleanupResult(fully_reaped=False, failures=("workspace: docker unreachable",)),
        started_before=_CUTOFF,
    )

    assert repository.saved == []
    assert agg.failed_with is None


@pytest.mark.unit
@pytest.mark.anyio
async def test_an_execution_started_after_this_process_is_never_a_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coordinator can dispatch new work in this same event loop.

    The read model cannot tell work orphaned by the previous process from work
    this one just started - both are RUNNING - so the cutoff is what separates
    them.
    """
    fresh = _Summary("exec-fresh", started_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC))
    old = _Summary("exec-old", started_at=datetime(2026, 9, 3, 3, 15, tzinfo=UTC))
    _, repository = _install(
        monkeypatch,
        [fresh, old],
        {"exec-fresh": _StubAggregate("exec-fresh"), "exec-old": _StubAggregate("exec-old")},
    )

    await reconcile_orphaned_executions(
        _REAPED, started_before=datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
    )

    assert repository.saved == ["exec-old"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_an_unparseable_start_time_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails closed: a stale row costs less than killing live work."""
    row = _Summary("exec-1")
    object.__setattr__(row, "started_at", "not-a-timestamp")
    _, repository = _install(monkeypatch, [row], {"exec-1": _StubAggregate("exec-1")})

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert repository.saved == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_the_failure_names_the_phase_that_was_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a phase id both phase read models keep the phase 'running' forever.

    `PhaseCompleted` is their only other writer, so a failure that does not name
    its phase leaves the execution terminal and the phase live (#1036).
    """
    agg = _StubAggregate("exec-1", running_phase_id="implement")
    _install(monkeypatch, [_Summary("exec-1")], {"exec-1": agg})

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert getattr(agg.failed_with, "failed_phase_id", "") == "implement"
