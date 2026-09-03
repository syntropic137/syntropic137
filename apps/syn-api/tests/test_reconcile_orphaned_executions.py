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
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

from syn_api.services.reconciliation import reconcile_orphaned_executions


@dataclass
class _Summary:
    workflow_execution_id: str
    completed_phases: int = 1
    total_phases: int = 3


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
    def __init__(self, execution_id: str, *, raises: bool = False) -> None:
        self.execution_id = execution_id
        self._raises = raises
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

    await reconcile_orphaned_executions()

    assert repository.saved == ["exec-1"]
    assert agg.failed_with is not None
    assert manager.workflow_execution_list.status_filter_seen == "running"


@pytest.mark.unit
@pytest.mark.anyio
async def test_the_reason_says_a_restart_did_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator reading the failed run must learn why without a code search."""
    agg = _StubAggregate("exec-1")
    _install(monkeypatch, [_Summary("exec-1")], {"exec-1": agg})

    await reconcile_orphaned_executions()

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

    await reconcile_orphaned_executions()

    assert repository.saved == ["exec-1", "exec-3"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_row_with_no_aggregate_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing is invented for a read-model row with no event stream behind it."""
    _, repository = _install(monkeypatch, [_Summary("exec-ghost")], {"exec-ghost": None})

    await reconcile_orphaned_executions()

    assert repository.saved == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_nothing_stranded_touches_no_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    _, repository = _install(monkeypatch, [], {})

    await reconcile_orphaned_executions()

    assert repository.saved == []
