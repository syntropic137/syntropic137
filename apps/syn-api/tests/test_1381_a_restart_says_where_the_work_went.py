"""The pointer to interrupted work has to outlive the process that saved it (#1381).

WHAT THIS IS ABOUT. The shutdown half of #1381 pushes whatever a dying
workspace holds that no remote has to ``refs/syn/lost/<execution>/<phase>``,
and says so at ERROR in the log of the process that is on its way out. That
log line was the only statement of the ref anyone ever got. On the other side
of the restart, `reconcile_orphaned_executions` fails the execution with a
reason that said nothing about it - so an operator reading a failed execution
saw "orphaned", with no way to learn from the record that the phase's commits
and edits had in fact been saved, or under what name.

WHY THAT IS A DEFECT AND NOT A NICETY. The recovery is performed by hand. A
ref nobody can be told the name of is, for the purpose of getting the work
back, the same as no ref: the bytes are in the origin and unreachable by any
route a person actually takes. Verification named this: the work survives the
restart but the execution cannot be continued or resumed with it.

WHAT IS PROVEN HERE, AND HOW. Not "a formatter was called". These tests run
the REAL quarantine gate against real git repositories with a real bare
origin, let it push a real ref, and then - in the same test, standing in for
the process that comes up afterwards - run the REAL `reconcile_orphaned_
executions` and take the ref name out of the failure reason it recorded on the
aggregate. That name is then handed to git, against the origin the first half
pushed to, and the saved commit and the saved file content are read back
through it. The two halves share no constant: the first writes the ref, the
second is asked where the work is, and the test only passes if what the second
says finds what the first wrote.

WHAT IS NOT PROVEN HERE. That the execution RESUMES. It does not: startup
reconciliation deliberately fails restart-stranded executions (#1120) because
nothing is left to execute their remaining phases. This closes the gap between
"the bytes are somewhere" and "the record says where", which is the part that
can be closed without changing what the aggregate decides.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_api.services.reconciliation import CleanupResult, reconcile_orphaned_executions
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _EXECUTION_ID,
    _PHASE_ID,
    _clone_repository,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    UnpushedWorkQuarantinedError,
)

if TYPE_CHECKING:
    from pathlib import Path

    from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
        _Clone,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_REAPED = CleanupResult(fully_reaped=True)
#: Every fixture row starts before this, so the startup cutoff never quietly
#: does the work an assertion claims to be doing.
_CUTOFF = datetime(2030, 1, 1, tzinfo=UTC)


@dataclass
class _Summary:
    workflow_execution_id: str = _EXECUTION_ID
    completed_phases: int = 1
    total_phases: int = 3
    started_at: datetime = datetime(2026, 9, 3, 3, 15, tzinfo=UTC)


class _StubExecutionList:
    def __init__(self, rows: list[_Summary]) -> None:
        self._rows = rows

    async def get_all(
        self, limit: int = 100, offset: int = 0, status_filter: str | None = None
    ) -> list[_Summary]:
        return self._rows[offset : offset + limit]


class _StubManager:
    def __init__(self, rows: list[_Summary]) -> None:
        self.workflow_execution_list = _StubExecutionList(rows)


class _RestartedAggregate:
    """The aggregate the NEXT process loads: still running, still on its phase.

    A double rather than the real aggregate because what is under test is the
    reason string reconciliation composes and records, not the aggregate's
    own rules - which this change deliberately does not touch. The one thing
    it has to be honest about is `running_phase_id`, because that is the half
    of the ref name the restart has to recover from durable state.
    """

    def __init__(self, execution_id: str, running_phase_id: str | None) -> None:
        self.execution_id = execution_id
        self.running_phase_id = running_phase_id
        self.stranded_deliverable = None
        self.failed_with: object | None = None

    def fail_execution(self, command: object) -> None:
        self.failed_with = command


class _StubRepository:
    def __init__(self, aggregate: _RestartedAggregate) -> None:
        self._aggregate = aggregate
        self.saved: list[str] = []

    async def get_by_id(self, aggregate_id: str) -> _RestartedAggregate | None:
        return self._aggregate if aggregate_id == self._aggregate.execution_id else None

    async def save(self, aggregate: _RestartedAggregate) -> None:
        self.saved.append(aggregate.execution_id)


async def _restart_and_read_the_reason(
    monkeypatch: pytest.MonkeyPatch,
    *,
    execution_id: str = _EXECUTION_ID,
    running_phase_id: str | None = _PHASE_ID,
) -> str:
    """Run the real startup reconciliation and return the reason it recorded.

    This is the second process. It has no workspace, no container, no clone
    and no memory of the one that died - which is the whole point: everything
    it can say about where the work went it has to derive from ids that were
    already durable.
    """
    aggregate = _RestartedAggregate(execution_id, running_phase_id)
    repository = _StubRepository(aggregate)
    monkeypatch.setattr(
        "syn_api._wiring.get_projection_mgr",
        lambda: _StubManager([_Summary(workflow_execution_id=execution_id)]),
    )
    monkeypatch.setattr(
        "syn_adapters.storage.repositories.get_workflow_execution_repository",
        lambda: repository,
    )

    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)

    assert repository.saved == [execution_id], "the restart did not terminalise the execution"
    command = aggregate.failed_with
    assert command is not None
    reason = command.error  # type: ignore[attr-defined]
    assert isinstance(reason, str)
    return reason


def _ref_named_in(reason: str) -> str:
    """The quarantine ref the failure reason points an operator at.

    Pulled OUT of the recorded reason rather than built from the same
    constants the first half used. If the restart named a ref that does not
    exist, this is the value git is about to fail on, which is exactly the
    failure mode worth catching.
    """
    candidates = [word.strip("'\".,") for word in reason.split() if "refs/syn/lost/" in word]
    assert candidates, f"the restart's failure reason names no quarantine ref:\n{reason}"
    return candidates[0]


def _origin_show(clone: _Clone, spec: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "show", spec],
        cwd=clone.origin,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def interrupted(tmp_path: Path) -> _Clone:
    """A phase's clone, up to date with its origin - before it does any work."""
    return _clone_repository(tmp_path)


async def test_the_restart_points_at_the_ref_the_shutdown_actually_pushed(
    interrupted: _Clone, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commit the dying process saved is reachable from the name the next one gives.

    The full hop, end to end and across the process boundary: the gate pushes,
    the reason is recorded by a function that shares no state with it, and the
    ref parsed back out of that reason resolves - in the origin - to the commit
    that would otherwise have died with the container.
    """
    stranded = interrupted.commit("stranded.py", "committed in the workspace, never pushed\n")
    with pytest.raises(UnpushedWorkQuarantinedError):
        await interrupted.run_gate()

    reason = await _restart_and_read_the_reason(monkeypatch)
    ref = _ref_named_in(reason)

    assert interrupted.reachable_in_origin(stranded, ref), (
        f"the restart pointed at {ref!r}, which does not lead to the interrupted "
        f"phase's commit {stranded!r} in the origin"
    )


async def test_the_uncommitted_edit_is_readable_through_the_name_the_restart_gives(
    interrupted: _Clone, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Content, not just reachability: the edited file reads back through that ref.

    An uncommitted edit is the shape with nothing else to find it by - it is
    on no branch and has no sha anyone could have written down - so the ref
    name is the entire recovery route for it.
    """
    (interrupted.path / "README.md").write_text("edited, never committed\n")
    with pytest.raises(UnpushedWorkQuarantinedError):
        await interrupted.run_gate()

    reason = await _restart_and_read_the_reason(monkeypatch)
    ref = _ref_named_in(reason)

    shown = _origin_show(interrupted, f"{ref}:README.md")
    assert shown.returncode == 0, (
        f"the restart named {ref!r} but the origin cannot read README.md through it: {shown.stderr}"
    )
    assert shown.stdout.strip() == "edited, never committed"


async def test_a_restart_that_names_the_wrong_phase_finds_nothing(
    interrupted: _Clone, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negative that makes the two above mean something.

    If the assertions passed for any ref, they would prove nothing about the
    NAME. So: the same saved work, the same origin, and a restart that
    believes a different phase was mid-flight. git must not find it. This is
    also the reason `running_phase_id` has to come off durable state rather
    than be guessed - a wrong phase is a lost recovery, silently.
    """
    interrupted.commit("stranded.py", "committed in the workspace, never pushed\n")
    with pytest.raises(UnpushedWorkQuarantinedError):
        await interrupted.run_gate()

    reason = await _restart_and_read_the_reason(monkeypatch, running_phase_id="some-other-phase")
    ref = _ref_named_in(reason)

    assert _origin_show(interrupted, f"{ref}^{{commit}}").returncode != 0, (
        f"{ref!r} resolved, so these tests would pass for a ref the shutdown never wrote"
    )


async def test_an_execution_with_no_phase_in_flight_is_promised_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No workspace was holding anything, so the record must not offer a ref.

    The failure still has to be recorded - that is #1120's guarantee and it is
    unchanged - but pointing an operator at a ref that cannot exist wastes the
    one recovery route they have and teaches them to distrust the others.
    """
    reason = await _restart_and_read_the_reason(monkeypatch, running_phase_id=None)

    assert "refs/syn/lost/" not in reason
    assert "Orphaned" in reason
