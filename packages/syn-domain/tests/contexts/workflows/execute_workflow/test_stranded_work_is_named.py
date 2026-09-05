"""#1200: a failed phase must say WHERE its work went, as data an API can read.

THE INCIDENT. `exec-9cfc47026881` ran for 27 minutes, pushed a complete branch,
then failed the #1167 output-artifact contract because it wrote no deliverable.
The failure record said only that the contract was unmet. The branch existed,
the work was finished, and nothing anywhere named it - so the run looked
identical to one that had produced nothing at all, and the work was found again
by a human reading a container log.

WHAT THESE TESTS DRIVE. The real `_fail_execution`, against REAL git
repositories (the harness #1184 already built for the completion path), and
then the real detail projection and its read model. A workspace double
returning canned stdout would only pin the double: it would stay green if the
claim were derived from a branch-name variable instead of from a ref that
exists on the remote, which is the single mistake this feature can make. Every
branch and SHA asserted below is read back out of the ORIGIN repository, never
copied from the value the code returned.

THREE STATES, NOT TWO, and they stay distinguishable all the way out:
  records - these locations are on a remote right now
  `[]`    - we asked git, and none of this phase's work is on a remote
  None    - nobody could ask (no workspace, or a workspace that stopped
            answering); the absence of a verdict is not a verdict of "nothing"
`[]` and None both render as "no recoverable branch", so prose alone cannot
tell them apart - which is why the API carries the structure and not a
sentence.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    PhaseDefinition,
    PushedWork,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    PhaseProducedNoDeclaredOutputError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _BRANCH,
    _REPO,
    _Clone,
    _clone_repository,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor as _make_smoke_processor
from .test_processor_smoke import _two_phase_workflow

if TYPE_CHECKING:
    from pathlib import Path

    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
        PhaseExecutionDetail,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: The execution in the issue, so a reader of a failure can find the incident.
_EXECUTION_ID = "exec-9cfc47026881"
_PHASE_ID = "implement"
_WORKFLOW_ID = "wf-1200"
_DECLARED = ("markdown",)


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
            workflow_name="Fix Issue",
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


async def _fail_with_workspace(workspace: object | None) -> WorkflowFailedEvent:
    """Drive the real #1167 failure with `workspace` still alive for the phase.

    Returns the `WorkflowFailedEvent` the aggregate emitted, because the event
    is where the fix has to land: a version that only put the branch in the
    exception message would satisfy an assertion on `str(error)` and change
    nothing an operator can query.
    """
    processor = _make_processor()
    processor._execution_repo.save = AsyncMock()  # keep the events inspectable
    if workspace is not None:
        processor._active_workspaces[_PHASE_ID] = workspace  # type: ignore[assignment]

    started_at = datetime.now(UTC) - timedelta(seconds=1671.8)
    processor._phase_started_at[_PHASE_ID] = started_at
    aggregate = _running_aggregate()

    await processor._fail_execution(
        error=PhaseProducedNoDeclaredOutputError(
            phase_id=_PHASE_ID, phase_name="Implement", declared=_DECLARED
        ),
        aggregate=aggregate,
        execution_id=_EXECUTION_ID,
        workflow_id=_WORKFLOW_ID,
        phases=[ExecutablePhase(phase_id=_PHASE_ID, name="Implement", order=1)],
        phase_results=[],
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=started_at,
        failed_phase_id=_PHASE_ID,
    )

    failed = [
        envelope.event
        for envelope in aggregate.get_uncommitted_events()
        if type(envelope.event).__name__ == "WorkflowFailedEvent"
    ]
    assert len(failed) == 1, "expected exactly one WorkflowFailedEvent"
    event = failed[0]
    assert isinstance(event, WorkflowFailedEvent)
    return event


async def _read_back(event: WorkflowFailedEvent) -> PhaseExecutionDetail:
    """The failed phase as the get_execution_detail API would serve it.

    Goes through the projection AND `WorkflowExecutionDetail.from_dict`, which
    is where a field that the projection stores but the read model forgets
    would disappear - #891's defect exactly, one hop further along.
    """
    detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    await detail.on_workflow_execution_started(
        {
            "execution_id": _EXECUTION_ID,
            "workflow_id": _WORKFLOW_ID,
            "workflow_name": "Fix Issue",
        }
    )
    await detail.on_phase_started(
        {"execution_id": _EXECUTION_ID, "phase_id": _PHASE_ID, "phase_name": "Implement"}
    )
    # Serialized exactly as production serializes it, so a field that survives
    # the event object but not `model_dump` is caught here.
    await detail.on_workflow_failed(WorkflowExecutionProcessor._serialize_event(event))

    execution = await detail.get_by_id(_EXECUTION_ID)
    assert execution is not None
    return next(p for p in execution.phases if p.workflow_phase_id == _PHASE_ID)


@pytest.fixture
def clone(tmp_path: Path) -> _Clone:
    """A phase's starting point: a clone on a feature branch, pushed and level.

    Its own fixture rather than an import of #1184's, so that the two suites
    can diverge without one silently reshaping the other's world.
    """
    return _clone_repository(tmp_path)


class _Unreachable:
    """A container that has stopped answering.

    Not a raise: the Docker backend RETURNS a non-zero result with empty
    stdout, which is byte-for-byte what a workspace with nothing pushed
    returns. That collision is the reason `None` and `[]` are different values.
    """

    async def execute(self, command: list[str]) -> ExecutionResult:
        return ExecutionResult(
            exit_code=1, success=False, duration_ms=0.0, stdout="", stderr="no such container"
        )


# ---------------------------------------------------------------------------
# (a) The work is on a remote: name the branch and the SHA.
# ---------------------------------------------------------------------------


async def test_a_pushed_branch_and_sha_are_named_on_the_failure(clone: _Clone) -> None:
    """The incident shape: pushed everything, wrote no deliverable, failed.

    The expected SHA is read from the ORIGIN's ref, not from the clone and not
    from the returned value, so this asserts the recorded commit is one a
    reader can actually fetch.
    """
    clone.commit("implementation.py", "the work the phase actually did\n")
    clone.git("push", "origin", _BRANCH)
    on_remote = clone.origin_refs()[f"refs/heads/{_BRANCH}"]

    failed = await _fail_with_workspace(clone.workspace)

    assert failed.pushed_work == [PushedWork(repo=_REPO, branch=_BRANCH, commit=on_remote)], (
        "the failure must name the branch and the commit the phase pushed; "
        f"got {failed.pushed_work!r}"
    )

    phase = await _read_back(failed)
    assert phase.pushed_work is not None
    assert [(w.branch, w.commit) for w in phase.pushed_work] == [(_BRANCH, on_remote)], (
        "the branch and SHA did not survive the projection and read model - "
        "the failure record is where an operator looks, not the log"
    )
    # And the prose says it too, for the reader who is not an API client.
    assert _BRANCH in phase.error_message and on_remote in phase.error_message  # type: ignore[operator]
    assert "declares output_artifacts" in (phase.error_message or ""), (
        "#1167's reason must survive alongside the location, not be replaced by it"
    )


async def test_the_reason_the_phase_failed_is_not_replaced_by_where_it_went(
    clone: _Clone,
) -> None:
    """#1167's message stays exactly as loud; #1200 is APPENDED to it."""
    clone.commit("implementation.py", "work\n")
    clone.git("push", "origin", _BRANCH)

    failed = await _fail_with_workspace(clone.workspace)

    message = failed.error_message
    assert message.index("produced none") < message.index(_BRANCH), (
        "the phase's own failure must come first; the location follows it"
    )


# ---------------------------------------------------------------------------
# (b) Nothing of this phase's work is on a remote: claim nothing.
# ---------------------------------------------------------------------------


async def test_a_phase_whose_work_never_reached_a_remote_claims_no_branch(
    clone: _Clone,
) -> None:
    """The trap this test exists to spring.

    The clone IS on a branch, that branch's NAME exists, and the branch exists
    on the remote - it was pushed when the phase started. What is not on any
    remote is the commit the phase made. A claim derived from "is the branch
    variable non-empty" is true here and useless: it would send a reader to a
    branch that does not contain the work.

    So the recorded answer must be the empty tuple - asked, and none of this
    phase's work is reachable - and the SHA must not be offered as somewhere
    to fetch from.
    """
    lost = clone.commit("implementation.py", "committed, never pushed\n")
    assert lost != clone.origin_refs()[f"refs/heads/{_BRANCH}"], (
        "this test is only meaningful while the local commit is off the remote"
    )

    failed = await _fail_with_workspace(clone.workspace)

    assert failed.pushed_work == [], (
        "a phase that pushed nothing must record 'checked, nothing there' - "
        f"got {failed.pushed_work!r}"
    )

    phase = await _read_back(failed)
    assert phase.pushed_work == ()
    assert lost not in (phase.error_message or ""), (
        "the failure offers an unpushed SHA as a place to fetch from"
    )
    assert _BRANCH not in (phase.error_message or ""), (
        "the failure names a branch that does not contain this phase's work"
    )


async def test_a_workspace_that_cannot_answer_records_no_verdict(clone: _Clone) -> None:
    """None, not `[]`: an inspection that could not run has found nothing out.

    Same operator-facing sentence as the case above ("no recoverable branch"),
    deliberately different data - which is the whole reason the API carries a
    nullable list rather than prose.
    """
    failed = await _fail_with_workspace(_Unreachable())

    assert failed.pushed_work is None, (
        "a workspace that stopped answering must not be recorded as 'nothing "
        f"was pushed'; got {failed.pushed_work!r}"
    )
    phase = await _read_back(failed)
    assert phase.pushed_work is None


async def test_a_failure_with_no_workspace_at_all_records_no_verdict() -> None:
    """A run that dies before provisioning has nobody to ask. Also None."""
    failed = await _fail_with_workspace(None)

    assert failed.pushed_work is None
    assert (await _read_back(failed)).pushed_work is None


# ---------------------------------------------------------------------------
# The inspection must never make the failure worse.
# ---------------------------------------------------------------------------


async def test_the_unreachable_workspace_still_fails_for_its_own_reason() -> None:
    """The inspection runs while the execution is already dying.

    An inspection that raised would replace "this phase produced none of its
    declared output" with "git could not be run" - a strictly worse error,
    about a different subject, on the path where the reader most needs the
    original.
    """
    failed = await _fail_with_workspace(_Unreachable())

    assert "produced none" in failed.error_message
    assert failed.error_type == "PhaseProducedNoDeclaredOutputError"


# ---------------------------------------------------------------------------
# (d) A phase that does its job never notices any of this exists.
# ---------------------------------------------------------------------------


async def test_a_phase_that_writes_its_deliverable_is_never_even_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The success path must not acquire a git inspection it does not need.

    Asserted by making the question itself fatal rather than by checking the
    happy path still ends `completed`: the inspection runs against a live
    container, and a version that ran it on every phase would cost every
    successful run a round of git and would still pass a status assertion.
    """

    def _never_ask(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the success path asked where a phase's work went")

    # Reached through `sys.modules` because the module and the class it holds
    # share a name, and importing that name gives the class.
    monkeypatch.setattr(
        sys.modules[WorkflowExecutionProcessor.__module__], "where_the_work_went", _never_ask
    )

    fake = FakeAgentExecutionHandler.success(
        produces=[("artifacts/output/deliverable.md", b"# Real output")]
    )
    processor = _make_smoke_processor(fake)

    result = await processor.run(
        workflow_id="wf-1200-unaffected",
        workflow_name="Produces Its Deliverable",
        phases=_two_phase_workflow(first_declares=("plan",), second_declares=("markdown",)),
        inputs={},
        execution_id="exec-1200-unaffected",
    )

    assert result.status == "completed", (
        f"Expected 'completed' but got '{result.status}' ({result.error_message!r})"
    )
    assert result.error_message is None
    assert fake.call_count == 2
    assert len(result.artifact_ids) == 2, (
        f"Expected one artifact per phase, got {result.artifact_ids}"
    )
