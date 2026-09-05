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
from typing import TYPE_CHECKING, cast
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
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    GitWorkspace,
    PhaseStartingPoint,
    record_phase_starting_point,
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


async def _provisioned(workspace: object) -> PhaseStartingPoint:
    """What the processor records the moment a workspace is handed to a phase.

    CALLED BEFORE THE PHASE DOES ANYTHING, in every test, because that ordering
    is the feature: a starting point read after the agent ran would contain the
    agent's own commits and attribute none of them to it. Tests therefore call
    this on their first line and commit afterwards, so the sequence a reader
    sees is the sequence production performs.
    """
    return await record_phase_starting_point(cast("GitWorkspace", workspace))


async def _fail_after(start: PhaseStartingPoint | None) -> WorkflowFailedEvent:
    """Drive the real #1167 failure for a phase that began at `start`.

    Returns the `WorkflowFailedEvent` the aggregate emitted, because the event
    is where the fix has to land: a version that only put the branch in the
    exception message would satisfy an assertion on `str(error)` and change
    nothing an operator can query.
    """
    processor = _make_processor()
    processor._execution_repo.save = AsyncMock()  # keep the events inspectable
    if start is not None:
        processor._phase_starting_points[_PHASE_ID] = start

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
    start = await _provisioned(clone.workspace)

    clone.commit("implementation.py", "the work the phase actually did\n")
    clone.git("push", "origin", _BRANCH)
    on_remote = clone.origin_refs()[f"refs/heads/{_BRANCH}"]

    failed = await _fail_after(start)

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
    start = await _provisioned(clone.workspace)
    clone.commit("implementation.py", "work\n")
    clone.git("push", "origin", _BRANCH)

    failed = await _fail_after(start)

    message = failed.error_message
    assert message.index("produced none") < message.index(_BRANCH), (
        "the phase's own failure must come first; the location follows it"
    )


# ---------------------------------------------------------------------------
# (b) The phase produced nothing: claim nothing, however pushed the branch is.
# ---------------------------------------------------------------------------


async def test_a_phase_that_produced_nothing_claims_no_branch(clone: _Clone) -> None:
    """The trap the first version of this feature walked into.

    The phase does NOTHING. It makes no commit, pushes nothing, and leaves the
    workspace exactly as it found it - on a feature branch whose commits an
    earlier phase already pushed. Every ingredient of a recoverable failure is
    present in git: HEAD exists, the branch has a name, and that name is on the
    remote containing HEAD. None of it is this phase's work.

    Answering "is HEAD on a remote" is therefore true here and worthless: it
    hands an operator a location for a phase that produced nothing, which makes
    "pushed complete work, wrote no deliverable" - recoverable, go and fetch it
    - and "produced nothing at all" - unrecoverable, run it again - the same
    record. That is the distinction the whole feature exists to draw, so the
    answer must be the empty tuple.
    """
    inherited = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    assert clone.git("rev-parse", "HEAD") == inherited, (
        "this test is only meaningful while the phase starts on a pushed branch"
    )

    start = await _provisioned(clone.workspace)
    # ... and then the phase does nothing at all.

    failed = await _fail_after(start)

    assert failed.pushed_work == [], (
        "a phase that produced nothing must record 'checked, nothing there' - "
        f"got {failed.pushed_work!r}"
    )

    phase = await _read_back(failed)
    assert phase.pushed_work == ()
    assert inherited not in (phase.error_message or ""), (
        "the failure offers the commit the phase INHERITED as its own output"
    )
    assert _BRANCH not in (phase.error_message or ""), (
        "the failure names a branch this phase put nothing on"
    )


async def test_a_phase_that_only_fetched_claims_no_branch(clone: _Clone) -> None:
    """Someone else's merged commit is not this phase's work either.

    A phase that fetches and resets onto a freshly advanced `origin/main` has a
    HEAD that IS on a remote ref - `origin/main` - and is new since it started,
    because the fetch happened after. Both halves of "new work that reached a
    remote" are satisfied by a phase that wrote nothing.

    What saves it is asking about the remote counterpart of THIS branch rather
    than about any remote ref: `origin/<branch>` does not contain that commit,
    so there is nothing to offer. A version that accepted any remote ref would
    name this phase's branch beside a SHA that branch does not contain - a
    location that is not merely useless but wrong, and one an operator would
    only discover by fetching it.
    """
    start = await _provisioned(clone.workspace)
    clone.advance_origin_main("someone_elses_pr.py", "merged while this ran\n")
    clone.git("reset", "--hard", "origin/main")
    on_a_remote = clone.git("rev-parse", "HEAD")
    assert on_a_remote == clone.origin_refs()["refs/heads/main"], (
        "this test is only meaningful while HEAD is a commit on some remote ref"
    )

    failed = await _fail_after(start)

    assert failed.pushed_work == [], (
        "a commit this phase merely fetched was reported as work it pushed - "
        f"got {failed.pushed_work!r}"
    )
    assert on_a_remote not in ((await _read_back(failed)).error_message or "")


# ---------------------------------------------------------------------------
# (c) It committed but never pushed: #1184's territory, and not recoverable here.
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
    start = await _provisioned(clone.workspace)
    lost = clone.commit("implementation.py", "committed, never pushed\n")
    assert lost != clone.origin_refs()[f"refs/heads/{_BRANCH}"], (
        "this test is only meaningful while the local commit is off the remote"
    )

    failed = await _fail_after(start)

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


async def test_the_offered_commit_is_the_one_the_remote_actually_holds(
    clone: _Clone,
) -> None:
    """Pushed, then committed again: offer the push, never the local tip.

    A phase that pushes and then keeps working ends with a HEAD that is NOT on
    any remote, and the two halves of its work have different fates: what it
    pushed is recoverable, what came after is #1184's problem. Reporting HEAD
    would send a reader to fetch a SHA that does not exist on the remote;
    reporting nothing would strand a branch that does.

    So the record names the newest commit the branch's remote is confirmed to
    hold, which is why `commit` is not documented as "HEAD".
    """
    start = await _provisioned(clone.workspace)
    clone.commit("implementation.py", "the work that got out\n")
    clone.git("push", "origin", _BRANCH)
    reached_the_remote = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    kept_local = clone.commit("polish.py", "committed after the push\n")

    failed = await _fail_after(start)

    assert failed.pushed_work == [
        PushedWork(repo=_REPO, branch=_BRANCH, commit=reached_the_remote)
    ], f"expected the pushed commit, not the local tip; got {failed.pushed_work!r}"
    assert kept_local not in ((await _read_back(failed)).error_message or ""), (
        "the failure offers a commit the remote does not have as a place to fetch from"
    )


async def test_a_workspace_that_cannot_answer_records_no_verdict(clone: _Clone) -> None:
    """None, not `[]`: an inspection that could not run has found nothing out.

    Same operator-facing sentence as the case above ("no recoverable branch"),
    deliberately different data - which is the whole reason the API carries a
    nullable list rather than prose.
    """
    failed = await _fail_after(await _provisioned(_Unreachable()))

    assert failed.pushed_work is None, (
        "a workspace that stopped answering must not be recorded as 'nothing "
        f"was pushed'; got {failed.pushed_work!r}"
    )
    phase = await _read_back(failed)
    assert phase.pushed_work is None


async def test_a_workspace_that_died_after_starting_records_no_verdict(
    clone: _Clone,
) -> None:
    """The other order, and it must not become a verdict of "nothing".

    The starting point was read fine; it is the failure-time half that cannot
    run, because the container went away between the two. There is now a real
    snapshot in hand and it is tempting to answer from it - but the snapshot
    only says what was NOT this phase's work. Whether the phase pushed anything
    is exactly what nobody can find out any more.
    """
    start = await _provisioned(clone.workspace)
    died = PhaseStartingPoint(
        workspace=cast("GitWorkspace", _Unreachable()), reachable=start.reachable
    )

    failed = await _fail_after(died)

    assert failed.pushed_work is None, (
        "a workspace that died mid-phase was recorded as one that pushed "
        f"nothing; got {failed.pushed_work!r}"
    )
    assert (await _read_back(failed)).pushed_work is None
    assert "produced none" in failed.error_message


async def test_a_failure_with_no_workspace_at_all_records_no_verdict() -> None:
    """A run that dies before provisioning has nobody to ask. Also None."""
    failed = await _fail_after(None)

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
    failed = await _fail_after(await _provisioned(_Unreachable()))

    assert "produced none" in failed.error_message
    assert failed.error_type == "PhaseProducedNoDeclaredOutputError"


# ---------------------------------------------------------------------------
# (d) The three outcomes are three values, not three sentences.
# ---------------------------------------------------------------------------


def _fresh(tmp_path: Path, name: str) -> Path:
    """A root of its own, because each case needs its own origin to be honest."""
    root = tmp_path / name
    root.mkdir()
    return root


async def test_the_three_outcomes_are_distinguishable_without_reading_prose(
    tmp_path: Path,
) -> None:
    """One client, three failures, three different answers to `pushed_work`.

    Each case above pins its own value; this pins that they DIFFER, which is
    the property an operator's tooling depends on and the one no single-case
    test can protect. It is easy to satisfy every assertion above with a field
    that quietly answers `[]` to two questions - "it produced nothing" and "it
    committed without pushing" being the pair most likely to collapse, since
    both phases end with nothing of theirs on a remote.

    They must not collapse INTO the pushed case: `[]` alongside a record would
    mean an operator who fetched nothing had been told there was nothing to
    fetch. Read through the projection and read model, because that is the
    shape the API serves.
    """
    pushed = _clone_repository(_fresh(tmp_path, "pushed"))
    pushed_start = await _provisioned(pushed.workspace)
    pushed.commit("implementation.py", "work that got out\n")
    pushed.git("push", "origin", _BRANCH)

    idle = _clone_repository(_fresh(tmp_path, "idle"))
    idle_start = await _provisioned(idle.workspace)

    local = _clone_repository(_fresh(tmp_path, "local"))
    local_start = await _provisioned(local.workspace)
    local.commit("implementation.py", "committed, never pushed\n")

    answers = {
        "pushed": (await _read_back(await _fail_after(pushed_start))).pushed_work,
        "produced nothing": (await _read_back(await _fail_after(idle_start))).pushed_work,
        "committed, unpushed": (await _read_back(await _fail_after(local_start))).pushed_work,
        "nobody could look": (await _read_back(await _fail_after(None))).pushed_work,
    }

    assert answers["pushed"], "the recoverable failure must name somewhere to look"
    assert answers["produced nothing"] == (), "asked, and this phase put nothing on a remote"
    assert answers["committed, unpushed"] == (), "its commits are local; #1184 quarantines them"
    assert answers["nobody could look"] is None, "the absence of a verdict is not a verdict"

    # And the one an API client actually acts on: recoverable vs not.
    assert (answers["pushed"] is not None and len(answers["pushed"]) > 0) and not any(
        answers[case] for case in ("produced nothing", "committed, unpushed", "nobody could look")
    ), f"a client cannot tell 'go and fetch it' from 'it is gone': {answers}"


# ---------------------------------------------------------------------------
# (e) A phase that does its job never notices any of this exists.
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


async def test_every_phase_records_where_it_started_before_its_agent_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hop the failure path cannot check for itself.

    `where_the_work_went` answers None when no starting point was recorded, and
    None is a legitimate answer - so a processor that never recorded one would
    make every failure say "nobody looked", and every test above that expects
    None would still pass. The wiring has to be pinned where it happens.

    ORDER IS THE POINT, not merely the call. A snapshot taken after the agent
    ran would contain the agent's own commits, and the phase would then be
    credited with nothing it did - the same silent, plausible emptiness by a
    different route. So the spy records how many agent runs had happened when
    it was asked, and the answer for phase N must be N.
    """
    module = sys.modules[WorkflowExecutionProcessor.__module__]
    real = module.record_phase_starting_point
    fake = FakeAgentExecutionHandler.success(
        produces=[("artifacts/output/deliverable.md", b"# Real output")]
    )
    agent_runs_before: list[int] = []

    async def _spy(workspace: object) -> object:
        agent_runs_before.append(fake.call_count)
        return await real(workspace)  # type: ignore[arg-type]

    monkeypatch.setattr(module, "record_phase_starting_point", _spy)

    processor = _make_smoke_processor(fake)
    result = await processor.run(
        workflow_id="wf-1200-provisioning",
        workflow_name="Records Where It Started",
        phases=_two_phase_workflow(first_declares=("plan",), second_declares=("markdown",)),
        inputs={},
        execution_id="exec-1200-provisioning",
    )

    assert result.status == "completed", f"{result.status}: {result.error_message!r}"
    assert agent_runs_before == [0, 1], (
        "each phase must record its starting point once, before its own agent "
        f"runs and after the previous one finished; got {agent_runs_before}"
    )
    assert processor._phase_starting_points == {}, (
        "starting points outlived their phases - a later failure would compare "
        "against a workspace that no longer exists"
    )
