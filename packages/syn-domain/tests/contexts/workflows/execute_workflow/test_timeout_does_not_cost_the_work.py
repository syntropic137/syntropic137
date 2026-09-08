"""#1231: hitting a phase's limit must cost time, not the commits it made.

THE INCIDENT. `exec-9cb32b4bbfe7` ran the implement phase of `sdlc-implement-v1`
for 3618s against a 3600s budget. The agent was killed (`exit_code=124`), the
phase reported two commits on no remote, and the workspace was destroyed with
them in it. `git log origin/fix/1179-predeploy-drain-check` is still at the
commit the phase started from. Eight of the last hundred executions ended that
way, $94.03 of agent time, and the only mitigation was a paragraph in the
prompt asking the agent to push early.

THE GAP WAS NEVER DETECTION. #1184 already knows how to push a dying
workspace's work somewhere durable and #1200 already reports where its branches
stand - but the first was wired only to the COMPLETION path, and a timeout
never reaches it: a non-zero exit becomes a `RuntimeError` in
`_handle_run_agent`, is caught by `run()`, and goes to `_fail_execution`, which
only ever LOOKED. So these tests drive the two terminal paths - failure and
cancellation - and assert against the ORIGIN repository, never against the
value the code returned. A double returning canned stdout would stay green if
the save were never pushed at all, which is the one mistake this can make.

WHAT IS DELIBERATELY NOT ASSERTED HERE is anything about the phase's own
branch. The work goes to `refs/syn/lost/<execution>/<phase>`, which nothing
fetches by default and no reviewer is shown, for the reason #1184 gives:
publishing half a task onto a branch under review is a different and worse
failure than losing it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    UnpushedWorkQuarantinedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _BRANCH,
    _clone_repository,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    GitWorkspace,
    refuse_to_complete_unsaved_phase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)

if TYPE_CHECKING:
    from pathlib import Path

    from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
        _Clone,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: The execution in the issue, so a reader of a failure can find the incident.
_EXECUTION_ID = "exec-9cb32b4bbfe7"
_PHASE_ID = "implement"
_WORKFLOW_ID = "sdlc-implement-v1"
_QUARANTINE_REF = f"refs/syn/lost/{_EXECUTION_ID}/{_PHASE_ID}"

#: What `_handle_run_agent` raises when the harness is killed at its limit.
#: 124 is coreutils `timeout`'s exit code and the convention the runner uses.
_TIMED_OUT = RuntimeError(
    f"Agent execution failed for phase {_PHASE_ID} (exit_code=124) (tokens=1804241+38112)"
)


@pytest.fixture
def clone(tmp_path: Path) -> _Clone:
    """A phase's starting point: a clone on a feature branch, pushed and level."""
    return _clone_repository(tmp_path)


def _make_processor() -> WorkflowExecutionProcessor:
    return WorkflowExecutionProcessor(
        execution_repository=AsyncMock(),
        session_repository=AsyncMock(),
        workspace_service=MagicMock(),
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="prompt"),
        command_builder=MagicMock(return_value=["claude"]),
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
    )


def _running_aggregate() -> WorkflowExecutionAggregate:
    agg = WorkflowExecutionAggregate()
    agg._handle_command(
        StartExecutionCommand(
            execution_id=_EXECUTION_ID,
            workflow_id=_WORKFLOW_ID,
            workflow_name="Make the change",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id=_PHASE_ID, name="Implement", order=1)],
        )
    )
    agg._handle_command(
        StartPhaseCommand(
            execution_id=_EXECUTION_ID,
            workflow_id=_WORKFLOW_ID,
            phase_id=_PHASE_ID,
            phase_name="Implement",
            phase_order=1,
        )
    )
    return agg


async def _provisioned(clone: _Clone) -> WorkflowExecutionProcessor:
    """A processor holding this clone exactly as `_handle_provision` leaves it.

    Both halves, in the order production sets them: the live workspace the
    terminal paths must be able to reach, and the starting point read BEFORE
    the phase does anything. A test that seeded only the second would pass
    against a save that read its workspace from the snapshot and never from
    the map teardown actually empties.
    """
    processor = _make_processor()
    processor._journal._repository.save = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    workspace = cast("GitWorkspace", clone.workspace)
    processor._runtime._workspaces[_PHASE_ID] = workspace  # type: ignore[assignment]
    await processor._runtime._starting_points.record(_PHASE_ID, workspace)  # pyright: ignore[reportPrivateUsage]
    processor._runtime._started_at[_PHASE_ID] = datetime.now(UTC) - timedelta(seconds=3618.39)
    return processor


async def _timed_out(
    processor: WorkflowExecutionProcessor, error: BaseException | None = None
) -> WorkflowFailedEvent:
    """Drive the real `_fail_execution` for a phase killed at its limit."""
    aggregate = _running_aggregate()
    await processor._fail_execution(
        error=cast("Exception", error or _TIMED_OUT),
        aggregate=aggregate,
        execution_id=_EXECUTION_ID,
        workflow_id=_WORKFLOW_ID,
        phases=[ExecutablePhase(phase_id=_PHASE_ID, name="Implement", order=1)],
        phase_results=[],
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=datetime.now(UTC) - timedelta(seconds=3618.39),
        failed_phase_id=_PHASE_ID,
    )
    failed = [
        envelope.event
        for envelope in aggregate.get_uncommitted_events()
        if isinstance(envelope.event, WorkflowFailedEvent)
    ]
    assert len(failed) == 1, "expected exactly one WorkflowFailedEvent"
    return failed[0]


# ---------------------------------------------------------------------------
# The incident: a timeout must not take the commits with it.
# ---------------------------------------------------------------------------


async def test_commits_a_timed_out_phase_never_pushed_survive_it(clone: _Clone) -> None:
    """THE ISSUE, reproduced: two commits, no push, killed at the limit.

    Asserted by reading the ORIGIN back - `merge-base --is-ancestor` against
    the quarantine ref is the same question that exited 1 for hours after the
    real incident. A phase that had merely been TOLD about the loss would
    still fail this line.
    """
    branch_head_before = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    processor = await _provisioned(clone)
    clone.commit("state_machine.py", "the first hour of work\n")
    lost = clone.commit("state_machine_test.py", "and the second\n")

    await _timed_out(processor)

    assert clone.reachable_in_origin(lost, _QUARANTINE_REF), (
        "the commits the phase made are not reachable from any ref in the "
        "origin - the timeout cost the work, which is #1231 itself"
    )
    assert clone.origin_refs()[f"refs/heads/{_BRANCH}"] == branch_head_before, (
        "half-finished work was published onto the branch under review"
    )


async def test_uncommitted_work_survives_a_timeout_too(clone: _Clone) -> None:
    """An agent killed mid-edit has not committed either, and that is the norm.

    The quarantine commit's tree is the WORKTREE as it stood, so the file must
    come back out of the origin with the bytes the agent left in it - read
    from the origin with `git show`, not from the workspace it was taken from.
    """
    processor = await _provisioned(clone)
    (clone.path / "half_written.py").write_text("def drain():  # cut off mid-edit\n")

    await _timed_out(processor)

    assert (
        clone.origin_git("show", f"{_QUARANTINE_REF}:half_written.py")
        == "def drain():  # cut off mid-edit"
    ), "the file the agent was editing when the limit fired did not survive"


async def test_the_failure_tells_the_operator_which_ref_to_fetch(clone: _Clone) -> None:
    """Saving it and not saying where is half the fix; the message is the other.

    The reason is the one an operator actually reads - it reaches the
    `WorkflowFailedEvent`, the phase result and the API - so the ref is
    asserted there rather than in a log line nobody queries.
    """
    processor = await _provisioned(clone)
    clone.commit("state_machine.py", "the work\n")

    failed = await _timed_out(processor)

    message = failed.error_message
    assert f"git fetch origin {_QUARANTINE_REF}" in message, (
        f"the failure does not tell the operator how to get the work back: {message}"
    )
    assert "exit_code=124" in message, (
        "the reason the phase died must survive alongside where its work went"
    )


async def test_a_phase_that_pushed_everything_is_told_of_no_quarantine(clone: _Clone) -> None:
    """Silence is a verdict too: nothing was held, so nothing is offered.

    A save that reported a ref for every failing phase would send operators to
    fetch refs that hold nothing, which is the same substitution #1200 refuses
    to make in the other direction.
    """
    processor = await _provisioned(clone)
    clone.commit("state_machine.py", "the work\n")
    clone.git("push", "origin", _BRANCH)

    failed = await _timed_out(processor)

    assert _QUARANTINE_REF not in failed.error_message, (
        "a phase holding nothing was offered a quarantine ref to fetch"
    )
    assert _QUARANTINE_REF not in clone.origin_refs(), (
        "an empty quarantine ref was pushed for a phase that had already pushed"
    )


async def test_the_ref_is_named_from_the_execution_and_phase_that_died(
    tmp_path: Path,
) -> None:
    """The ids reach the ref an operator has to fetch, through the failing hop.

    Both ids differ from this module's constants deliberately: a hop that
    named the ref from anything other than the failing execution and phase
    would still push something plausible, and every other test here would
    still be green.
    """
    clone = _clone_repository(tmp_path)
    processor = _make_processor()
    processor._journal._repository.save = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    processor._runtime._workspaces["verify"] = clone.workspace  # type: ignore[assignment]
    clone.commit("checked.py", "work from a different run\n")

    await processor._fail_execution(
        error=_TIMED_OUT,
        aggregate=_running_aggregate(),
        execution_id="exec-a-different-run",
        workflow_id=_WORKFLOW_ID,
        phases=[ExecutablePhase(phase_id="verify", name="Verify", order=1)],
        phase_results=[],
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=datetime.now(UTC),
        failed_phase_id="verify",
    )

    refs = clone.origin_refs()
    assert "refs/syn/lost/exec-a-different-run/verify" in refs, (
        f"the ref was named from something other than the dying phase: {sorted(refs)}"
    )
    assert _QUARANTINE_REF not in refs


async def test_a_phase_that_was_not_the_one_that_died_is_left_alone(tmp_path: Path) -> None:
    """Only the failing phase's workspace is emptied, not every live one.

    The processor is shared across concurrent executions, so the map holds
    other runs' workspaces. Quarantining those would push refs naming this
    execution over another's work and empty a container that is still running.
    """
    roots = {name: tmp_path / name for name in ("dying", "running")}
    for root in roots.values():
        root.mkdir()
    dying = _clone_repository(roots["dying"])
    running = _clone_repository(roots["running"])
    running.commit("elsewhere.py", "another execution's work, still in progress\n")

    processor = _make_processor()
    processor._journal._repository.save = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    processor._runtime._workspaces[_PHASE_ID] = dying.workspace  # type: ignore[assignment]
    processor._runtime._workspaces["review"] = running.workspace  # type: ignore[assignment]

    await _timed_out(processor)

    assert [ref for ref in running.origin_refs() if ref.startswith("refs/syn/lost/")] == [], (
        "a phase that was still running had its workspace quarantined"
    )


# ---------------------------------------------------------------------------
# The other terminal path. Cancelling tears the same workspace down.
# ---------------------------------------------------------------------------


async def test_cancelling_an_execution_does_not_destroy_its_commits(clone: _Clone) -> None:
    """`_cancel_execution` closes the same workspaces `_fail_execution` does.

    A user who cancels a run that is going the wrong way still wants the hour
    of work it did, and until this the cancel path went straight to
    `abandon_all` - the identical defect one method along.
    """
    processor = await _provisioned(clone)
    lost = clone.commit("state_machine.py", "an hour of work, then cancelled\n")

    result = await processor._cancel_execution(
        _EXECUTION_ID,
        _WORKFLOW_ID,
        [],
        [],
        datetime.now(UTC),
        cancel_reason="Cancelled by user",
        phase_id=_PHASE_ID,
    )

    assert clone.reachable_in_origin(lost, _QUARANTINE_REF), (
        "cancelling destroyed the commits the phase had made"
    )
    assert f"git fetch origin {_QUARANTINE_REF}" in (result.error_message or ""), (
        "the cancelled execution does not say where its work went"
    )
    assert "Cancelled by user" in (result.error_message or ""), (
        "why it was cancelled must survive alongside where the work went"
    )


# ---------------------------------------------------------------------------
# The completion gate already saved. Doing it twice contradicts itself.
# ---------------------------------------------------------------------------


async def test_work_the_completion_gate_already_saved_is_not_pushed_twice(
    clone: _Clone,
) -> None:
    """#1184's refusal IS a failure, and it arrives here with the work already out.

    The gate quarantines and then raises, and that exception becomes this
    failure's reason - so the recovery ref is ALREADY in the message before
    the terminal path does anything. Saving again finds the same work (a
    quarantine pushes outside `refs/remotes`, so git still calls those commits
    unpushed) and appends a second report of it, naming one ref twice with two
    different headlines. An operator reading a message that says the same
    commits were saved twice cannot tell whether there were two saves.

    ASSERTED ON THE COUNT, not on the ref's value, because the ref usually
    does not move: `_IDENTITY` fixes the author and committer, so the second
    `commit-tree` differs from the first only in its timestamp and is the
    identical object whenever both land in the same whole second. When they
    do not, the differing commit is pushed WITHOUT force over a ref it is not
    a descendant of, is rejected as a non-fast-forward, and prints "NONE OF IT
    IS RECOVERABLE" directly beneath the gate's "All of it is recoverable".
    The duplicate report happens every time; the contradiction happens on a
    clock boundary. Both are the same second save, so this catches both.
    """
    processor = await _provisioned(clone)
    saved = clone.commit("state_machine.py", "committed, never pushed\n")

    with pytest.raises(UnpushedWorkQuarantinedError) as refused:
        await refuse_to_complete_unsaved_phase(
            processor._runtime.live_workspaces,
            TodoItem(
                execution_id=_EXECUTION_ID,
                action=TodoAction.COMPLETE_PHASE,
                phase_id=_PHASE_ID,
                session_id="sess-1",
            ),
        )
    gate_pushed = clone.origin_refs()[_QUARANTINE_REF]

    failed = await _timed_out(processor, error=refused.value)

    recovery = f"recover with: git fetch origin {_QUARANTINE_REF}"
    assert failed.error_message.count(recovery) == 1, (
        "the work was saved a second time and reported twice under one "
        f"failure, once per save: {failed.error_message}"
    )
    assert clone.origin_refs()[_QUARANTINE_REF] == gate_pushed, (
        "the ref the gate pushed was overwritten or moved by a second save"
    )
    assert clone.reachable_in_origin(saved, _QUARANTINE_REF)
    assert "NOT RECOVERABLE" not in failed.error_message, (
        "a second quarantine push was rejected and reported the work as lost, "
        f"under a message that already said where it is: {failed.error_message}"
    )
