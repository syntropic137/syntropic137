"""#1200: a failed phase must say WHERE its branches stand, as data an API can read.

THE INCIDENT. `exec-9cfc47026881` ran for 27 minutes, pushed a complete branch,
then failed the #1167 output-artifact contract because it wrote no deliverable.
The failure record said only that the contract was unmet. The branch existed,
the work was finished, and nothing anywhere named it - so the run looked
identical to one that had produced nothing at all, and the work was found again
by a human reading a container log.

OBSERVATIONS, NOT ATTRIBUTIONS, and that is what these tests pin hardest. Two
earlier versions of this feature reported "the work THIS PHASE pushed", derived
by snapshotting the refs at provisioning and calling anything new the phase's
own. GIT DOES NOT RECORD WHO PUSHED A COMMIT: a concurrent process, or a
person, pushing to the same branch between the two readings produces the
identical evidence. So what is recorded is what was read - the branch, where
its remote ref is now, where it was when the phase started, and how many local
commits no remote has - and the assertions below check that nothing claims
more. An operator needs to know where to look; that never required knowing
whose push it was.

WHAT THESE TESTS DRIVE. The real `_fail_execution`, against REAL git
repositories (the harness #1184 already built for the completion path), and
then the real detail projection and its read model. A workspace double
returning canned stdout would only pin the double: it would stay green if a
reading were derived from a branch-name variable instead of from a ref that
exists, which is the single mistake this feature can make. Every branch and SHA
asserted below is read back out of the ORIGIN repository, never copied from the
value the code returned.

FOUR STATES, NOT THREE, and they stay distinguishable all the way out:
  a moved ref  - `origin/<branch>` is not where the phase found it: fetch it
  unpushed     - commits here are on no remote: #1184's quarantine, nothing to
                 fetch, and NOT the same incident as nothing having happened
  `[]`         - we read git, and every branch is where the phase found it
  None         - nobody could read it; the absence of a verdict is not a
                 verdict of "nothing changed"
The last three all render as "no branch to fetch", so prose alone cannot tell
them apart - which is why the API carries the structure and not a sentence.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    BranchObservation,
    ExecutablePhase,
    PhaseDefinition,
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
from syn_domain.contexts.orchestration.slices.execute_workflow import unpushed_work_guard
from syn_domain.contexts.orchestration.slices.execute_workflow import (
    unpushed_work_guard as guard,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    PhaseProducedNoDeclaredOutputError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
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
    PhaseStartingPoints,
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


async def _provisioned(workspace: object) -> PhaseStartingPoints:
    """What the processor records the moment a workspace is handed to a phase.

    CALLED BEFORE THE PHASE DOES ANYTHING, in every test, because that ordering
    is the feature: a starting point read after the agent ran would already
    hold whatever the agent pushed, and every ref would then look unmoved.
    Tests therefore call this on their first line and commit afterwards, so the
    sequence a reader sees is the sequence production performs.

    Returns the registry rather than the reading, because the registry is what
    the processor owns: `record` here is the same call `_handle_provision`
    makes, so these tests fail if that recording stops working.
    """
    points = PhaseStartingPoints()
    await points.record(_PHASE_ID, cast("GitWorkspace", workspace))
    return points


def _holding(start: PhaseStartingPoint) -> PhaseStartingPoints:
    """A registry seeded with a reading the test built by hand.

    Only for the cases that need a starting point production could not produce
    - a snapshot paired with a workspace that has since died. Everything else
    goes through `_provisioned`, which takes the reading the real way.
    """
    points = PhaseStartingPoints()
    points._by_phase[_PHASE_ID] = start
    return points


async def _fail_after(start: PhaseStartingPoints | None) -> WorkflowFailedEvent:
    """Drive the real #1167 failure for a phase that began at `start`.

    Returns the `WorkflowFailedEvent` the aggregate emitted, because the event
    is where the fix has to land: a version that only put the branch in the
    exception message would satisfy an assertion on `str(error)` and change
    nothing an operator can query.
    """
    processor = _make_processor()
    # keep the events inspectable
    processor._journal._repository.save = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    if start is not None:
        processor._runtime._starting_points = start  # pyright: ignore[reportPrivateUsage]

    started_at = datetime.now(UTC) - timedelta(seconds=1671.8)
    processor._runtime._started_at[_PHASE_ID] = started_at  # pyright: ignore[reportPrivateUsage]
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
    await detail.on_workflow_failed(ExecutionJournal._serialize_event(event))

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
    stdout, which is byte-for-byte what a workspace with nothing to report
    returns. That collision is the reason `None` and `[]` are different values.
    """

    async def execute(self, command: list[str]) -> ExecutionResult:
        return ExecutionResult(
            exit_code=1, success=False, duration_ms=0.0, stdout="", stderr="no such container"
        )


# ---------------------------------------------------------------------------
# (a) The remote ref moved: name the branch, where it is, and where it was.
# ---------------------------------------------------------------------------


async def test_a_moved_remote_ref_is_named_with_both_of_its_commits(clone: _Clone) -> None:
    """The incident shape: pushed everything, wrote no deliverable, failed.

    Both SHAs are read from the ORIGIN's ref, never from the clone and never
    from the returned value, so this asserts the recorded commits are ones a
    reader can actually fetch and compare.
    """
    started_at = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    start = await _provisioned(clone.workspace)

    clone.commit("implementation.py", "the work the phase actually did\n")
    clone.git("push", "origin", _BRANCH)
    on_remote = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    assert on_remote != started_at, "this test is only meaningful while the ref moved"

    failed = await _fail_after(start)

    assert failed.observed_branches == [
        BranchObservation(
            repo=_REPO,
            branch=_BRANCH,
            remote="origin",
            remote_commit=on_remote,
            remote_commit_at_phase_start=started_at,
            unpushed_commits=0,
        )
    ], (
        "the failure must record the branch, where its remote ref is now, and "
        f"where it was at phase start; got {failed.observed_branches!r}"
    )

    phase = await _read_back(failed)
    assert phase.observed_branches is not None
    assert [
        (w.branch, w.remote_commit, w.remote_commit_at_phase_start) for w in phase.observed_branches
    ] == [(_BRANCH, on_remote, started_at)], (
        "the branch and both SHAs did not survive the projection and read "
        "model - the failure record is where an operator looks, not the log"
    )


async def test_the_operator_is_told_what_was_observed_and_not_who_did_it(
    clone: _Clone,
) -> None:
    """The prose makes the same claim the data does, and no larger one.

    THE POINT OF THE THIRD PASS. "This phase pushed <sha>" is not a sentence
    git can support: a ref that advanced between two readings advanced, and
    nothing records whose push advanced it. So the message states the two
    readings and lets the reader conclude - and both SHAs must be in it,
    because a message naming only the current one is the attribution again
    with the evidence removed.
    """
    started_at = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    start = await _provisioned(clone.workspace)
    clone.commit("implementation.py", "the work the phase actually did\n")
    clone.git("push", "origin", _BRANCH)
    on_remote = clone.origin_refs()[f"refs/heads/{_BRANCH}"]

    message = (await _read_back(await _fail_after(start))).error_message or ""

    assert f"the remote branch origin/{_BRANCH} is at {on_remote}" in message, (
        f"the failure must say where the branch IS, as an observation: {message}"
    )
    assert f"differs from {started_at} when the phase started" in message, (
        f"the failure must say what it is being compared against: {message}"
    )
    for claim in ("this phase pushed", "its own work", "produced by this phase"):
        assert claim not in message.lower(), (
            f"the failure claims authorship git cannot support ({claim!r}): {message}"
        )
    assert "declares output_artifacts" in message, (
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
# The reading is of the REMOTE, not of this clone's cache of it.
# ---------------------------------------------------------------------------


async def test_external_push_without_fetch_reports_actual_remote_tip(clone: _Clone) -> None:
    """The blocking finding of the fourth pass, as an input the fixtures omitted.

    Every other test here moves the branch by pushing FROM the phase clone,
    and a push updates that clone's `refs/remotes` as a side effect. So the
    cache and the remote agreed in every fixture, and reading the cache passed
    all of them while answering a different question: `refs/remotes` says what
    this clone was last told, and it advances only when this clone fetches or
    pushes.

    Here someone else pushes - a second clone of the same origin, which is a
    teammate, a rerun, or a bot - and the phase clone never fetches. Its cache
    still holds the commit it started at, the origin holds another, and the
    two are now different questions with different answers. The record must
    carry the ORIGIN's answer, because that is the commit an operator will
    find when they go and fetch; the cached one is not on the remote's branch
    any more and sends them to the wrong place.
    """
    started_at = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    start = await _provisioned(clone.workspace)

    actual_now = clone.push_from_elsewhere("someone_elses_push.py", "pushed from another clone\n")

    assert clone.origin_refs()[f"refs/heads/{_BRANCH}"] == actual_now != started_at, (
        "this test is only meaningful while the origin really moved"
    )
    assert clone.cached_remote_tip() == started_at, (
        "this test is only meaningful while this clone's cache is STALE - it "
        "must not have fetched, or there is no difference left to detect"
    )

    failed = await _fail_after(start)

    assert failed.observed_branches == [
        BranchObservation(
            repo=_REPO,
            branch=_BRANCH,
            remote="origin",
            remote_commit=actual_now,
            remote_commit_at_phase_start=started_at,
            unpushed_commits=0,
        )
    ], (
        "the record must hold the commit the ORIGIN points at, not the one "
        f"this clone last heard about ({started_at}); got {failed.observed_branches!r}"
    )

    phase = await _read_back(failed)
    assert phase.observed_branches is not None
    (record,) = phase.observed_branches
    assert record.remote_commit == actual_now, (
        "the origin's commit reached the event but not the read model - the "
        "hop that drops a value, one past the one this test is about"
    )
    assert f"is at {actual_now}" in (phase.error_message or ""), (
        "the operator is sent to a commit the remote does not hold"
    )


async def test_an_unreachable_remote_is_not_answered_from_the_cache(clone: _Clone) -> None:
    """Asking the remote is a NETWORK call, and it can simply fail.

    The trap it opens is the defect itself wearing a fallback: this clone HAS
    a cached ref, it is right there, and offering it when the remote does not
    answer produces a record that looks exactly like a successful reading. It
    would be a commit nobody confirmed, printed as where the branch is.

    So a remote that cannot be reached yields no verdict - the same `None` the
    API already carries for "nobody could look", which is honest here because
    nobody could. The reason says which question went unanswered, so an
    unreachable REMOTE is still tellable from an unreachable WORKSPACE by a
    reader, and the cached commit appears nowhere.
    """
    start = await _provisioned(clone.workspace)
    clone.commit("implementation.py", "the work the phase actually did\n")
    clone.git("push", "origin", _BRANCH)
    cached = clone.cached_remote_tip()
    assert cached == clone.origin_refs()[f"refs/heads/{_BRANCH}"], (
        "the push must have left a cached ref, or there is no fallback to resist"
    )

    clone.break_the_remote()

    failed = await _fail_after(start)

    assert failed.observed_branches is None, (
        "a remote that could not be asked was answered from the cache; the "
        f"stale reading must not become a record - got {failed.observed_branches!r}"
    )

    phase = await _read_back(failed)
    assert phase.observed_branches is None
    message = phase.error_message or ""
    assert cached not in message, f"the cached commit is offered as where the branch is: {message}"
    assert f"asking origin where {_BRANCH} is" in message, (
        f"the failure does not say WHICH question went unanswered: {message}"
    )
    assert "ls-remote" in message, (
        f"the reason must name the command, so a reader can tell an unreachable "
        f"remote from an unreachable container: {message}"
    )
    assert "produced none" in message, (
        "#1167's reason must survive a remote that could not be reached"
    )


async def test_a_hanging_remote_cannot_hold_up_the_failing_phase(
    clone: _Clone, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Teardown is queued behind this read, so the read must end by itself.

    A remote that REFUSES is over in milliseconds and proves nothing about a
    bound. A remote that accepts and then says nothing is the one that hangs,
    and until it is bounded the phase's container stays up for as long as the
    other end feels like - on a path that only runs when something has already
    gone wrong.

    The hang here is thirty seconds and the bound is one, so the elapsed time
    is the assertion: anything near thirty means nothing cut it off. What the
    phase then reports is the same absence of a verdict any unanswered command
    produces, and #1167's own reason is still the reason it failed.
    """
    monkeypatch.setattr(guard, "_REMOTE_TIMEOUT_SECONDS", 1)
    start = await _provisioned(clone.workspace)
    clone.hang_the_remote(seconds=30)

    began = time.monotonic()
    failed = await _fail_after(start)
    elapsed = time.monotonic() - began

    assert elapsed < 15, (
        f"the read waited {elapsed:.1f}s on a remote that never answers - the "
        "bound is not being applied, and teardown waits behind this"
    )
    assert failed.observed_branches is None, (
        f"a remote that never answered produced a verdict: {failed.observed_branches!r}"
    )
    message = (await _read_back(failed)).error_message or ""
    assert "timed out, so it did not finish" in message, (
        f"a bound that fired must read as one, not as an exit code: {message}"
    )
    assert "produced none" in message, "#1167's reason must survive a remote that never answered"


# ---------------------------------------------------------------------------
# (b) Nothing changed anywhere: record nothing, and offer no inherited SHA.
# ---------------------------------------------------------------------------


async def test_a_workspace_nothing_touched_records_no_branch(clone: _Clone) -> None:
    """The trap the first version of this feature walked into.

    The phase does NOTHING. It makes no commit, pushes nothing, and leaves the
    workspace exactly as it found it - on a feature branch whose commits an
    earlier phase already pushed. Every ingredient of a recoverable failure is
    present in git: HEAD exists, the branch has a name, and that name is on the
    remote containing HEAD.

    Answering "is HEAD on a remote" is therefore true here and worthless: it
    hands an operator a location for a workspace nothing happened in, which
    makes "a branch moved, go and fetch it" and "nothing here changed" the same
    record. So the answer must be the empty tuple, and the SHA the phase
    INHERITED must appear nowhere - it is not a difference, and reporting it
    would be reporting a fact about the clone as if it were about the run.
    """
    inherited = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    assert clone.git("rev-parse", "HEAD") == inherited, (
        "this test is only meaningful while the phase starts on a pushed branch"
    )

    start = await _provisioned(clone.workspace)
    # ... and then the phase does nothing at all.

    failed = await _fail_after(start)

    assert failed.observed_branches == [], (
        "a workspace nothing touched must record 'read, and nothing differs' - "
        f"got {failed.observed_branches!r}"
    )

    phase = await _read_back(failed)
    assert phase.observed_branches == ()
    assert inherited not in (phase.error_message or ""), (
        "the failure offers the commit the phase INHERITED as somewhere to look"
    )
    assert _BRANCH not in (phase.error_message or ""), (
        "the failure names a branch that is exactly where the phase found it"
    )


async def test_a_phase_that_only_fetched_records_no_branch(clone: _Clone) -> None:
    """Someone else's merged commit is not this workspace's incident either.

    A phase that fetches and resets onto a freshly advanced `origin/main` HAS
    moved a remote-tracking ref - `origin/main` is at a commit it was not at
    when the phase started - and its HEAD is now a commit that is on a remote.
    Every ingredient of "a ref moved" is present, produced by a phase that
    wrote nothing.

    What saves it is observing the remote counterpart of THIS branch and no
    other ref: `origin/<branch>` did not move, and nothing local is off a
    remote. A version that reported every ref it saw move would put another
    PR's merge in this phase's failure record, which is worse than useless -
    an operator would fetch it and find someone else's work.
    """
    start = await _provisioned(clone.workspace)
    clone.advance_origin_main("someone_elses_pr.py", "merged while this ran\n")
    clone.git("reset", "--hard", "origin/main")
    someone_else = clone.git("rev-parse", "HEAD")
    assert someone_else == clone.origin_refs()["refs/heads/main"], (
        "this test is only meaningful while a remote ref really did move"
    )

    failed = await _fail_after(start)

    assert failed.observed_branches == [], (
        "a ref this phase merely fetched was reported as this workspace's "
        f"business - got {failed.observed_branches!r}"
    )
    assert someone_else not in ((await _read_back(failed)).error_message or "")


# ---------------------------------------------------------------------------
# (c) Commits on no remote: a DIFFERENT record from (b), and not fetchable.
# ---------------------------------------------------------------------------


async def test_commits_that_no_remote_holds_are_recorded_as_such(clone: _Clone) -> None:
    """The blocking finding this pass exists to fix.

    The clone IS on a branch, that branch's name exists, and the branch exists
    on the remote - it was pushed before the phase started. What is not on any
    remote is the commit made here. Until now this answered `[]`, exactly like
    the workspace nothing touched, and the two are NOT the same incident: this
    one is holding work that dying will destroy (#1184's quarantine territory),
    and the other has nothing.

    So it records a branch, and the record says what is true of it: the remote
    ref is where the phase found it, AND commits here are on no remote. Both
    halves matter - the second is the incident, and the first is what stops a
    reader fetching a branch that does not contain them.
    """
    unchanged = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    start = await _provisioned(clone.workspace)
    lost = clone.commit("implementation.py", "committed, never pushed\n")
    assert lost != clone.origin_refs()[f"refs/heads/{_BRANCH}"], (
        "this test is only meaningful while the local commit is off the remote"
    )

    failed = await _fail_after(start)

    assert failed.observed_branches == [
        BranchObservation(
            repo=_REPO,
            branch=_BRANCH,
            remote="origin",
            remote_commit=unchanged,
            remote_commit_at_phase_start=unchanged,
            unpushed_commits=1,
        )
    ], (
        "unpushed commits must be recorded as their own observation, not "
        f"flattened into 'nothing changed'; got {failed.observed_branches!r}"
    )

    phase = await _read_back(failed)
    assert phase.observed_branches is not None
    (record,) = phase.observed_branches
    assert record.unpushed_commits == 1
    assert not record.remote_moved, "the remote ref did not move and must not be said to have"

    message = phase.error_message or ""
    assert "1 commit here on no remote at all" in message, (
        f"the failure does not say the commits are unreachable: {message}"
    )
    assert lost not in message, "the failure offers an unpushed SHA as a place to fetch from"
    assert "git fetch" not in message, (
        "the failure offers a fetch for a branch that does not contain the work"
    )


async def test_the_offered_commit_is_the_one_the_remote_actually_holds(
    clone: _Clone,
) -> None:
    """Pushed, then committed again: report the ref, never the local tip.

    A phase that pushes and then keeps working ends with a HEAD that is NOT on
    any remote, and the two halves of its work have different fates: what
    reached the remote is fetchable, what came after is #1184's problem.
    Reporting HEAD would send a reader to fetch a SHA the remote does not have;
    reporting only the ref would hide that something is about to be lost.

    So one record says both, which is why `remote_commit` is not documented as
    "HEAD".
    """
    start = await _provisioned(clone.workspace)
    clone.commit("implementation.py", "the work that got out\n")
    clone.git("push", "origin", _BRANCH)
    reached_the_remote = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    kept_local = clone.commit("polish.py", "committed after the push\n")

    failed = await _fail_after(start)

    assert failed.observed_branches is not None
    (record,) = failed.observed_branches
    assert record.remote_commit == reached_the_remote, (
        f"expected the commit the ref holds, not the local tip; got {record!r}"
    )
    assert record.unpushed_commits == 1, (
        f"the commit made after the push is on no remote and must be counted; got {record!r}"
    )
    assert kept_local not in ((await _read_back(failed)).error_message or ""), (
        "the failure offers a commit the remote does not have as a place to fetch from"
    )


# ---------------------------------------------------------------------------
# Nobody could look: None, never an empty answer.
# ---------------------------------------------------------------------------


async def test_a_workspace_that_cannot_answer_records_no_verdict(clone: _Clone) -> None:
    """None, not `[]`: an inspection that could not run has found nothing out.

    Same operator-facing sentence as the case above ("no branch to fetch"),
    deliberately different data - which is the whole reason the API carries a
    nullable list rather than prose.
    """
    failed = await _fail_after(await _provisioned(_Unreachable()))

    assert failed.observed_branches is None, (
        "a workspace that stopped answering must not be recorded as 'nothing "
        f"changed'; got {failed.observed_branches!r}"
    )
    phase = await _read_back(failed)
    assert phase.observed_branches is None


async def test_a_workspace_that_died_after_starting_records_no_verdict(
    clone: _Clone,
) -> None:
    """The other order, and it must not become a verdict of "nothing changed".

    The starting point was read fine; it is the failure-time half that cannot
    run, because the container went away between the two. There is now a real
    snapshot in hand and it is tempting to answer from it - but a snapshot is
    half a comparison. Where those refs point NOW is exactly what nobody can
    find out any more.
    """
    start = await record_phase_starting_point(cast("GitWorkspace", clone.workspace))
    died = PhaseStartingPoint(
        workspace=cast("GitWorkspace", _Unreachable()), remote_refs=start.remote_refs
    )

    failed = await _fail_after(_holding(died))

    assert failed.observed_branches is None, (
        "a workspace that died mid-phase was recorded as one where nothing "
        f"changed; got {failed.observed_branches!r}"
    )
    assert (await _read_back(failed)).observed_branches is None
    assert "produced none" in failed.error_message


async def test_a_failure_with_no_workspace_at_all_records_no_verdict() -> None:
    """A run that dies before provisioning has nobody to ask. Also None."""
    failed = await _fail_after(None)

    assert failed.observed_branches is None
    assert (await _read_back(failed)).observed_branches is None


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
# (d) The four outcomes are four values, not four sentences.
# ---------------------------------------------------------------------------


def _fresh(tmp_path: Path, name: str) -> Path:
    """A root of its own, because each case needs its own origin to be honest."""
    root = tmp_path / name
    root.mkdir()
    return root


async def test_the_four_outcomes_are_distinguishable_without_reading_prose(
    tmp_path: Path,
) -> None:
    """One client, four failures, four different answers to `observed_branches`.

    Each case above pins its own value; this pins that they DIFFER, which is
    the property an operator's tooling depends on and the one no single-case
    test can protect.

    THE PAIR THAT COLLAPSED. "Nothing changed anywhere" and "commits are here
    that no remote has" both end with nothing of this phase's on a remote, and
    both answered `[]` until this pass - so a client could not tell a workspace
    holding doomed work from one holding none. They are asserted UNEQUAL below,
    not merely each equal to their own value: two constants can drift into
    agreement while both single-case tests still pass.

    Read through the projection and read model, because that is the shape the
    API serves.
    """
    moved = _clone_repository(_fresh(tmp_path, "moved"))
    moved_start = await _provisioned(moved.workspace)
    moved.commit("implementation.py", "work that got out\n")
    moved.git("push", "origin", _BRANCH)

    idle = _clone_repository(_fresh(tmp_path, "idle"))
    idle_start = await _provisioned(idle.workspace)

    local = _clone_repository(_fresh(tmp_path, "local"))
    local_start = await _provisioned(local.workspace)
    local.commit("implementation.py", "committed, never pushed\n")

    answers = {
        "ref moved": (await _read_back(await _fail_after(moved_start))).observed_branches,
        "nothing changed": (await _read_back(await _fail_after(idle_start))).observed_branches,
        "committed, unpushed": (await _read_back(await _fail_after(local_start))).observed_branches,
        "nobody could look": (await _read_back(await _fail_after(None))).observed_branches,
    }

    assert len({repr(value) for value in answers.values()}) == 4, (
        f"four incidents must be four structured values, not fewer: {answers}"
    )
    assert answers["nothing changed"] != answers["committed, unpushed"], (
        "a client cannot tell a workspace holding doomed commits from one "
        f"holding nothing: {answers}"
    )

    # And what a client actually acts on, read off the structure alone.
    def _verdict(value: tuple[BranchObservation, ...] | None) -> str:
        if value is None:
            return "go and check by hand"
        if any(record.remote_moved for record in value):
            return "fetch it"
        if any(record.unpushed_commits for record in value):
            return "it is being quarantined, nothing to fetch"
        return "nothing happened here"

    assert {case: _verdict(value) for case, value in answers.items()} == {
        "ref moved": "fetch it",
        "nothing changed": "nothing happened here",
        "committed, unpushed": "it is being quarantined, nothing to fetch",
        "nobody could look": "go and check by hand",
    }, f"a client cannot act differently on the four incidents: {answers}"


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
        raise AssertionError("the success path asked where a phase's branches stood")

    # Patched where the question is asked rather than where it is wired in, so
    # this fails for ANY success-path caller, not only the one wired today.
    monkeypatch.setattr(unpushed_work_guard, "observe_branches", _never_ask)

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

    `observe_branches` answers None when no starting point was recorded, and
    None is a legitimate answer - so a processor that never recorded one would
    make every failure say "nobody looked", and every test above that expects
    None would still pass. The wiring has to be pinned where it happens.

    ORDER IS THE POINT, not merely the call. A snapshot taken after the agent
    ran would already hold whatever the agent pushed, and every ref would then
    read as unmoved - the same silent, plausible emptiness by a different
    route. So the spy records how many agent runs had happened when it was
    asked, and the answer for phase N must be N.
    """
    real = unpushed_work_guard.record_phase_starting_point
    fake = FakeAgentExecutionHandler.success(
        produces=[("artifacts/output/deliverable.md", b"# Real output")]
    )
    agent_runs_before: list[int] = []

    async def _spy(workspace: object) -> object:
        agent_runs_before.append(fake.call_count)
        return await real(workspace)  # type: ignore[arg-type]

    monkeypatch.setattr(unpushed_work_guard, "record_phase_starting_point", _spy)

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
    assert not processor._runtime._starting_points._by_phase, (  # pyright: ignore[reportPrivateUsage]
        "starting points outlived their phases - a later failure would compare "
        "against a workspace that no longer exists"
    )
