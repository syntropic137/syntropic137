"""#1381: recreating the API container must interrupt a phase, not erase it.

THE INCIDENT IS THE DEPLOY ITSELF. Every deploy of the selfhost stack recreates
the api container, and until this change a running execution did not survive it:
`BackgroundWorkflowDispatcher.shutdown` cancels each task, `CancelledError` is a
`BaseException`, and `run()`'s `except Exception` therefore never sees it. So
neither terminal path ran - no quarantine push, no teardown - and an ephemeral
workspace was reclaimed holding the only copy of the phase's commits. The cost
was not the crash, it was the WAITING: the deploy had to drain the platform
first, which took about two hours against a swap that takes 52 seconds.

WHAT THESE TESTS DRIVE is the real `run()` loop, cancelled while an agent is
genuinely suspended mid-phase, against REAL git repositories. Nothing here
mocks the preservation and nothing asserts that a function was called: every
claim about the work is read back out of the ORIGIN afterwards, which is the
same `merge-base --is-ancestor` question that exited 1 after the #1231
incident. A double returning canned stdout would stay green if the push never
happened at all.

THE COMPANION TEST, `apps/syn-api/tests/test_1381_a_real_sigterm_keeps_the_work
.py`, drives an actual SIGTERM at an actual process running the real dispatcher.
It reuses the harness below. These two are not redundant: this module pins what
the interrupted execution does, that one pins that a signal reaches it.

SIGTERM, NOT SIGKILL. Both live in the same frame as the phase, so both cover
the same thing: an interruption that still runs Python. A SIGKILL or an OOM runs
none, and no in-process hook can preserve anything against it - what survives a
SIGKILL is only what was already durable when it landed.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from typing import TYPE_CHECKING, cast

import pytest

from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow import workspace_git
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _BRANCH,
    _clone_repository,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import FakeExecutionRepository, _make_processor

#: The processor MODULE, which is where the backstop's value lives. Imported by
#: full name because the slice package re-exports the class under the module's
#: own name, so an attribute lookup would find the class instead.
processor_module = importlib.import_module(
    "syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor"
)

if TYPE_CHECKING:
    from pathlib import Path

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
        _Clone,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: A deploy that recreated the api container while this execution was running.
EXECUTION_ID = "exec-1381-interrupted-by-deploy"
PHASE_ID = "implement"
WORKFLOW_ID = "sdlc-implement-v1"
QUARANTINE_REF = f"refs/syn/lost/{EXECUTION_ID}/{PHASE_ID}"


def one_phase_holding_a_repository() -> list[ExecutablePhase]:
    """One phase that declares no output artifact, as the smoke harness does.

    `output_artifact_types=()` because the agent double here never returns at
    all, so it writes nothing; declaring an output would make the completion
    gate (#1167) the reason these runs end rather than the restart.
    """
    return [
        ExecutablePhase(
            phase_id=PHASE_ID,
            name="Implement",
            order=1,
            description="The phase a deploy interrupts",
            agent_config=AgentConfiguration(),
            prompt_template="make the change",
            output_artifact_types=(),
            timeout_seconds=3600,
        )
    ]


class GitBackedWorkspace:
    """A memory workspace whose GIT commands reach a real repository on disk.

    Split by the one thing that distinguishes them: every command the
    preservation path issues goes through `workspace_git.run_bounded`, which
    puts `timeout` at the front of the argv, and nothing else in the processor
    does. Those - and only those - run for real against the clone; provisioning,
    file injection and artifact collection stay with the memory backend.

    THE SPLIT IS WHAT MAKES THIS SAFE AS WELL AS USEFUL. Hydration runs setup
    scripts that write all over an absolute `/workspace` prefix, which on a test
    machine is the machine's own. `_Workspace` rewrites two prefixes and nothing
    else, so sending everything to it would run those scripts against the host.
    """

    def __init__(self, inner: ManagedWorkspace, clone: _Clone) -> None:
        self._inner = inner
        self._clone = clone

    async def execute(self, command: list[str], **kwargs: object) -> ExecutionResult:
        if command[:1] == ["timeout"]:
            return await self._clone.workspace.execute(command)
        return await self._inner.execute(command, **kwargs)  # type: ignore[arg-type]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class WatchedWorkspaces:
    """The real workspace service, with each phase's workspace git-backed.

    Records whether every context it opened was CLOSED, because that is the
    other half of #1381 that no git assertion can see: the processor holds
    workspaces as manually-entered context managers, so a `CancelledError` that
    unwound past the terminal paths leaked the container as well as the commits.
    """

    def __init__(self, inner: object, clone: _Clone) -> None:
        self._inner = inner
        self._clone = clone
        self.open_contexts = 0
        self.closed_contexts = 0

    def create_workspace(self, **kwargs: object) -> WatchedWorkspaces._Context:
        return self._Context(self, self._inner.create_workspace(**kwargs))  # type: ignore[attr-defined]

    class _Context:
        def __init__(self, owner: WatchedWorkspaces, inner: object) -> None:
            self._owner = owner
            self._inner = inner

        async def __aenter__(self) -> object:
            workspace = await self._inner.__aenter__()  # type: ignore[attr-defined]
            self._owner.open_contexts += 1
            return GitBackedWorkspace(workspace, self._owner._clone)

        async def __aexit__(self, *exc_info: object) -> bool | None:
            self._owner.closed_contexts += 1
            return await self._inner.__aexit__(*exc_info)  # type: ignore[attr-defined]


def watched_workspaces(clone: _Clone) -> WatchedWorkspaces:
    """The production workspace service the smoke harness uses, wrapped."""
    return WatchedWorkspaces(WorkspaceService.create(backend=WorkspaceBackend.MEMORY), clone)


class Interrupted:
    """A `run()` in flight, its agent suspended, ready to be interrupted."""

    def __init__(
        self,
        task: asyncio.Task[object],
        executions: FakeExecutionRepository,
        workspaces: WatchedWorkspaces,
    ) -> None:
        self.task = task
        self.executions = executions
        self.workspaces = workspaces

    async def restart(self) -> None:
        """Do to this execution exactly what `dispatcher.shutdown()` does to it.

        Cancel, then WAIT - and assert the task saw the cancellation, because a
        `run()` that returned a result instead would mean the restart had been
        converted into a verdict about the execution, which is the one thing
        preservation must not do.
        """
        self.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await self.task


async def interrupt_a_running_phase(
    clone: _Clone, *, execution_id: str = EXECUTION_ID
) -> Interrupted:
    """Start a real execution and return once its agent is genuinely running.

    Returns before anything is cancelled so the caller can make the work that
    has to survive - commits, edits - at the moment production makes it: after
    the phase is under way and before the restart arrives.
    """
    running = asyncio.Event()
    executions = FakeExecutionRepository()
    workspaces = watched_workspaces(clone)
    processor = _make_processor(
        FakeAgentExecutionHandler.still_running(running),
        execution_repository=executions,
        workspace_service=workspaces,
    )
    task = asyncio.ensure_future(
        processor.run(
            workflow_id=WORKFLOW_ID,
            workflow_name="Make the change",
            phases=one_phase_holding_a_repository(),
            inputs={},
            execution_id=execution_id,
        )
    )
    await asyncio.wait_for(running.wait(), timeout=60)
    return Interrupted(cast("asyncio.Task[object]", task), executions, workspaces)


@pytest.fixture
def clone(tmp_path: Path) -> _Clone:
    """A phase's starting point: a clone on a feature branch, pushed and level."""
    return _clone_repository(tmp_path)


# ---------------------------------------------------------------------------
# The incident: a deploy must not take the phase's work with it.
# ---------------------------------------------------------------------------


async def test_commits_an_interrupted_phase_never_pushed_survive_the_restart(
    clone: _Clone,
) -> None:
    """THE ISSUE, reproduced: an hour of work, no push, and then a deploy.

    Read back from the ORIGIN, because that is the only place "survived" can
    mean anything: the container the commit was made in is gone by the time
    this assertion runs, which is precisely why the deploy used to cost it.
    """
    branch_head_before = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    interrupted = await interrupt_a_running_phase(clone)
    clone.commit("state_machine.py", "the first hour of work\n")
    lost = clone.commit("state_machine_test.py", "and the second\n")

    await interrupted.restart()

    assert clone.reachable_in_origin(lost, QUARANTINE_REF), (
        "the commits the phase made are reachable from no ref in the origin - "
        "the restart cost the work, which is #1381 itself"
    )
    assert clone.origin_refs()[f"refs/heads/{_BRANCH}"] == branch_head_before, (
        "half-finished work was published onto the branch under review"
    )


async def test_uncommitted_work_survives_the_restart_too(clone: _Clone) -> None:
    """An agent interrupted mid-edit has not committed either, and that is the norm.

    The bytes come back out of the origin with `git show`, not off the
    workspace they were taken from.
    """
    interrupted = await interrupt_a_running_phase(clone)
    (clone.path / "half_written.py").write_text("def drain():  # cut off by the deploy\n")

    await interrupted.restart()

    assert (
        clone.origin_git("show", f"{QUARANTINE_REF}:half_written.py")
        == "def drain():  # cut off by the deploy"
    ), "the file the agent was editing when the container went did not survive"


async def test_the_interrupted_phase_does_not_leak_its_workspace(clone: _Clone) -> None:
    """The container half of the same defect, and it has no other witness.

    The processor holds each phase's workspace as a manually-entered context
    manager, so the `CancelledError` that skipped the terminal paths skipped
    `__aexit__` with them: the api process exited leaving the phase's container
    and its sidecar running, on a host about to start a new api. Asserted on
    the context rather than on docker because the context is the hop - a
    teardown that ran and failed is a different report, not a leak.
    """
    interrupted = await interrupt_a_running_phase(clone)
    clone.commit("state_machine.py", "an hour of work\n")

    await interrupted.restart()

    assert interrupted.workspaces.open_contexts == 1, "the phase never got a workspace"
    assert interrupted.workspaces.closed_contexts == 1, (
        "the interrupted phase's workspace context was never exited - the "
        "container outlived the process that was holding it"
    )


# ---------------------------------------------------------------------------
# What the aggregate decides is NOT this change's business (requirement 3).
# ---------------------------------------------------------------------------


async def test_an_interrupted_execution_is_left_resumable_not_judged(clone: _Clone) -> None:
    """A restart is not a verdict, so the aggregate must still say RUNNING.

    THE CHEAPEST WRONG VERSION of this fix reports the interrupted execution
    as cancelled or failed on the way out, because that makes the read model
    tidy. It is neither: nobody asked for it to stop and nothing about it
    failed, and a `cancelled` execution is one no restart will ever pick up -
    which turns preserving the work into losing the run that owns it. Leaving
    it RUNNING is what `StaleExecutionCleaner` already exists to decide about,
    and deciding is its job and not this path's.

    Read out of the REPOSITORY, not off the return value: `run()` re-raises, so
    there is no return value here at all, and the only durable record of what
    the restart left behind is the saved aggregate (ADR-060).
    """
    interrupted = await interrupt_a_running_phase(clone)
    clone.commit("state_machine.py", "an hour of work\n")

    await interrupted.restart()

    saved = await interrupted.executions.get_by_id(EXECUTION_ID)
    assert saved is not None, "the interrupted execution was never persisted at all"
    assert saved.status == ExecutionStatus.RUNNING, (
        f"the restart decided the execution was {saved.status} - preservation is "
        "an infrastructure concern and must not issue a verdict the aggregate "
        "owns; an execution moved to a terminal state is one no restart resumes"
    )


async def test_a_user_cancellation_still_ends_up_cancelled(clone: _Clone) -> None:
    """The verdict that IS a verdict must keep arriving (#663, #918).

    `interrupt_requested` travels through the aggregate and comes back as
    `status='cancelled'`, and the new interrupted path must not intercept it:
    the two look alike from inside `run()` and mean opposite things. A fix that
    routed a cooperative cancel through the restart path would raise here
    instead of returning, and this is the test that would say so.
    """
    processor = _make_processor(
        FakeAgentExecutionHandler.cancelled(),
        workspace_service=watched_workspaces(clone),
    )
    clone.commit("state_machine.py", "an hour of work, then cancelled by a user\n")

    result = await processor.run(
        workflow_id=WORKFLOW_ID,
        workflow_name="Make the change",
        phases=one_phase_holding_a_repository(),
        inputs={},
        execution_id="exec-1381-cancelled-by-a-user",
    )

    assert result.status == "cancelled", (
        f"a user cancellation reported '{result.status}'; the restart path has "
        "taken over a decision the aggregate makes"
    )


async def test_an_agent_killed_at_its_limit_still_fails(clone: _Clone) -> None:
    """Exit 124 is still a failure, and its own reason must still be the reason.

    The mirror of the test above on the other terminal path. `CancelledError`
    and a non-zero exit arrive at `run()` through different `except` clauses
    now, and the new one sits above the old: a branch that caught too much
    would turn every timeout into a silent interruption with no failure
    recorded anywhere.
    """
    processor = _make_processor(
        FakeAgentExecutionHandler.failed(exit_code=124),
        workspace_service=watched_workspaces(clone),
    )
    clone.commit("state_machine.py", "3618 seconds against a 3600 second budget\n")

    result = await processor.run(
        workflow_id=WORKFLOW_ID,
        workflow_name="Make the change",
        phases=one_phase_holding_a_repository(),
        inputs={},
        execution_id="exec-1381-killed-at-its-limit",
    )

    assert result.status == "failed", (
        f"a phase killed at its limit reported '{result.status}'; the restart "
        "path has swallowed a real failure"
    )
    assert "124" in (result.error_message or ""), (
        f"the reason the phase died did not survive: {result.error_message!r}"
    )


# ---------------------------------------------------------------------------
# The shutdown has to END. Preservation must not become the new drain.
# ---------------------------------------------------------------------------


class _NeverAnswers:
    """A workspace whose git commands hang OUTSIDE the walk's own bounds.

    Every command the save issues carries `timeout` in its argv, so the walk
    cannot hang by itself - the hang has to come from the layer underneath,
    which is what a docker daemon that has stopped answering actually is. This
    is the only way to stage that, and it is the case the backstop exists for.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner

    async def execute(self, command: list[str], **kwargs: object) -> ExecutionResult:
        if command[:1] == ["timeout"]:
            await asyncio.sleep(30)
        return await self._inner.execute(command, **kwargs)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


async def test_a_workspace_that_stops_answering_cannot_hold_the_deploy_open(
    clone: _Clone, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1381 arriving from the other side: an unbounded shutdown IS the bug.

    The whole point of the change is that a deploy no longer waits for the
    platform to drain. A preservation step that can hang gives that back with
    interest - `shutdown()` waits for every task, so one workspace nobody can
    reach would hold the new api container out indefinitely, which is worse
    than the two hours it replaced.

    Thirty seconds of hang against a budget of one, so the ELAPSED TIME is the
    assertion: anything near thirty means nothing cut it off. The cancellation
    must still propagate afterwards - a backstop that swallowed it would leave
    `gather` waiting on a task that never reports.
    """
    monkeypatch.setattr(processor_module, "_PRESERVATION_BUDGET_SECONDS", 1.0)
    monkeypatch.setattr(workspace_git, "LOCAL_TIMEOUT_SECONDS", 1)
    interrupted = await interrupt_a_running_phase(clone)
    workspace = interrupted.workspaces
    clone.commit("state_machine.py", "an hour of work\n")
    # Swapped in only now: provisioning has to have finished for real, and it
    # is teardown that meets the dead daemon.
    held = _NeverAnswers(clone.workspace)
    monkeypatch.setattr(clone, "workspace", held, raising=False)

    began = time.monotonic()
    await interrupted.restart()
    elapsed = time.monotonic() - began

    assert elapsed < 15, (
        f"the shutdown waited {elapsed:.1f}s on a workspace that never answers - "
        "the deploy it was meant to unblock is blocked again"
    )
    assert workspace.open_contexts == 1
