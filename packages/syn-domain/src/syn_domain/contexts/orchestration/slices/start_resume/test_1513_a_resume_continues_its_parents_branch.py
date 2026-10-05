"""A resumed phase continues the branch and PR its parent's attempt pushed (#1513).

A v3 implement phase opens a draft PR on its first push. A parent that failed
in implement after that left branch B and PR N behind, and a resume that
started implement fresh opened a second branch and a second PR for one change.

These drive the real chain, faking only the two boundaries: the workspace's
`execute` (a git simulator, `_World`) and the GitHub HTTP client behind the
production `GitHubRemoteBranchReader`. Prompts and agent commands are built
by the production `_wiring` builders, so the child decides what to do from
the argv it was launched with, as an agent would. The parent's agent pushes B and opens
PR N through that world; `PhaseStartingPoints` records and observes it with
real git commands, and the failure path asks the real reader which PR is open.

    world: B pushed, PR N open -> PhaseStartingPoints.observe (git argv)
      -> with_open_pull_requests (reader) -> WorkflowFailed.observed_branches,
      stored as JSON and read back
      -> aggregate's left branches -> `StartResumeCommand` candidates
      -> `StartResumeHandler` asks the forge -> the child's start event
      -> `StartPins.checkout_for` -> provisioning -> `.setup/setup.sh`
      -> `record_continuation` -> the phase's context
      -> `_build_workspace_prompt` -> `_build_agent_command` -> the agent's argv
      -> the child commits and pushes B, advancing PR N's head

Harness shared with #1458, whose pinned-commit chain this extends.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ConfigDict

from syn_adapters.github.client import GitHubAppError
from syn_adapters.github.remote_branch_reader import GitHubRemoteBranchReader
from syn_adapters.workspace_backends.memory.memory_adapter import MemoryIsolationAdapter
from syn_adapters.workspace_backends.service.pinned_checkout import pinned_heads
from syn_api._wiring import _build_agent_command, _build_workspace_prompt
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    AbandonedBranch,
    ContinuedBranch,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ResumeExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
    IsolationHandle,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.start_resume import StartResumeHandler
from syn_domain.contexts.orchestration.slices.start_resume.test_1458_a_resume_is_provisioned_at_its_parents_commits import (
    _checkout_line,
    _Executions,
    _phase,
    _processor,
    _ReadsItsSetup,
)
from syn_domain.contexts.orchestration.slices.start_resume.test_1458_a_resume_is_provisioned_at_its_parents_commits import (
    _FakeGitHubClient as _FakeGitHubClient,
)
from syn_domain.contexts.orchestration.slices.start_resume.test_1458_a_resume_is_provisioned_at_its_parents_commits import (
    _github_app as _github_app,  # autouse fixture: a GitHub App that mints tokens
)
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler
from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration import AgentExecutionResult
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import Runner
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

PARENT = "exec-1513-parent"
CHILD = "exec-1513-child"
WORKFLOW = "wf-1513"
PHASE_IDS = ("research", "implement", "review")

REPO = "syntropic137/pinned-repo"
DEST = "/workspace/repos/pinned-repo"
PINNED = "5e1f0c3a9b2d47e68f01a2b3c4d5e6f708192a3b"
BRANCH = "feat/1513-continue-me"
#: Where the parent's implement attempt left BRANCH on origin.
PUSHED = "b1513b1513b1513b1513b1513b1513b1513b1513"
#: The commit the child's implement makes on top of PUSHED.
CHILD_COMMIT = "c1513c1513c1513c1513c1513c1513c1513c1513"
PR = 4242
#: A PR someone else opened from BRANCH after the parent's was closed.
OTHER_PR = 4343
MAIN_SHA = "a" * 40


class _World:
    """Origin, one clone of it, and the PRs on the forge: the exec and HTTP boundary.

    Answers the git argv `workspace_git` builds the way git would, records
    every command, and serves the GitHub endpoints the production reader asks.
    Anything else a workspace runs succeeds with no output, as the in-memory
    backend always did.
    """

    def __init__(self) -> None:
        self.origin: dict[str, str] = {"main": MAIN_SHA}
        self.cache: dict[str, str] = {"origin/main": MAIN_SHA}
        self.local: dict[str, str] = {"main": MAIN_SHA}
        self.head = "main"
        #: The commit HEAD is detached at, when it is not on a branch.
        self.detached: str | None = None
        self.pulls: dict[str, list[tuple[int, str]]] = {}
        self.readable = True
        self.commands: list[list[str]] = []

    # -- what the agents do -------------------------------------------------

    def push_and_open_pr(self) -> None:
        """The parent's implement: create B, push it, open draft PR N."""
        self.local[BRANCH] = PUSHED
        self.head = BRANCH
        self.detached = None
        self.origin[BRANCH] = PUSHED
        self.cache[f"origin/{BRANCH}"] = PUSHED
        self.pulls[BRANCH] = [(PR, "open")]

    def close_and_reopen_as_another_pr(self) -> None:
        self.pulls[BRANCH] = [(PR, "closed"), (OTHER_PR, "open")]

    def _commit(self) -> str:
        self.local[self.head] = CHILD_COMMIT
        return ""

    def _push(self, refspec: str) -> str:
        """`git push origin HEAD:<b>`: origin's b, and every PR from it, move to HEAD."""
        branch = refspec.removeprefix("HEAD:")
        self.origin[branch] = self.local[self.head]
        self.cache[f"origin/{branch}"] = self.local[self.head]
        return ""

    # -- the exec boundary --------------------------------------------------

    def check_out(self, script: str) -> None:
        """What the setup script leaves the clone at: on BRANCH if it continues it,
        else detached at its pin (#967 reads HEAD back and holds the run to it)."""
        if f"checkout --quiet -B {BRANCH}" in script:
            self.head, self.detached = BRANCH, None
            self.local[BRANCH] = self.origin[BRANCH]
        else:
            self.detached = pinned_heads(script).get(DEST, self.detached)

    def run(self, command: list[str]) -> ExecutionResult:
        self.commands.append(list(command))
        if "-C" not in command:
            out = f"{DEST}/.git\n" if "find" in command else ""
            return _ok(out)
        args = command[command.index("-C") + 2 :]
        return _ok(self._git(args))

    def _git(self, args: list[str]) -> str:
        match args:
            case ["for-each-ref", fmt, "refs/remotes"] if "objectname" in fmt:
                return "".join(f"{sha} {ref}\n" for ref, sha in self.cache.items())
            case ["for-each-ref", _, "refs/heads"]:
                return "".join(f"{b}\n" for b in self.local)
            case ["rev-parse", "--abbrev-ref", "HEAD"]:
                return "HEAD" if self.detached else self.head
            case ["rev-parse", "--symbolic-full-name", "HEAD"]:
                return "HEAD" if self.detached else f"refs/heads/{self.head}"
            case ["rev-parse", "--verify", ref] if ref.startswith("refs/remotes/"):
                return self.cache[ref.removeprefix("refs/remotes/")]
            case ["rev-parse", *_]:
                return self.detached or self.local[self.head]
            case ["remote"]:
                return "origin\n"
            case ["commit", *_]:
                return self._commit()
            case ["push", "origin", refspec]:
                return self._push(refspec)
            case ["ls-remote", "origin", ref]:
                name = ref.removeprefix("refs/heads/")
                return f"{self.origin[name]}\t{ref}\n" if name in self.origin else ""
            case _:
                return ""

    # -- the HTTP boundary (GitHubAppClient) --------------------------------

    async def get_installation_for_repo(self, full_name: str) -> str:
        assert full_name == REPO
        if not self.readable:
            raise GitHubAppError("GitHub API error 503: unavailable")
        return "inst-1513"

    async def api_get(self, path: str, installation_id: str) -> object:
        del installation_id
        branch = BRANCH.replace("/", "%2F")
        if path == f"/repos/{REPO}/branches/{branch}":
            if BRANCH not in self.origin:
                raise GitHubAppError("GitHub API error 404: Branch not found")
            return {"commit": {"sha": self.origin[BRANCH]}}
        assert path.startswith(f"/repos/{REPO}/pulls?head=syntropic137:{branch}"), path
        return [{"number": n, "state": st} for n, st in self.pulls.get(BRANCH, [])]

    def reader(self) -> GitHubRemoteBranchReader:
        return GitHubRemoteBranchReader(lambda: self)  # type: ignore[arg-type,return-value]

    # -- what the assertions read -------------------------------------------

    def pushes(self) -> list[list[str]]:
        """Branch pushes, not the platform's own dry-run credential rehearsal."""
        return [c for c in self.commands if "push" in c and "--dry-run" not in c]

    def opened_prs(self) -> list[list[str]]:
        return [c for c in self.commands if c[:3] == ["gh", "pr", "create"]]

    def open_prs_from(self, branch: str) -> list[tuple[int, str]]:
        """Each open PR from ``branch`` and its head: a PR's head is its branch on origin."""
        return [(n, self.origin[branch]) for n, st in self.pulls.get(branch, []) if st == "open"]


def _ok(stdout: str) -> ExecutionResult:
    return ExecutionResult(exit_code=0, success=True, duration_ms=1.0, stdout=stdout, stderr="")


@pytest.fixture
def world() -> Iterator[_World]:
    the_world = _World()

    async def execute(
        self: MemoryIsolationAdapter, handle: IsolationHandle, command: list[str], **_: object
    ) -> ExecutionResult:
        if command == ["bash", "/workspace/.setup/setup.sh"]:
            the_world.check_out(
                self._instances[handle.isolation_id].files[".setup/setup.sh"].decode()
            )
        return the_world.run(command)

    with patch.object(MemoryIsolationAdapter, "execute", execute):
        yield the_world


@dataclass
class _Acts(_ReadsItsSetup):
    """Reads its setup, then acts on the argv it was launched with, then its scripted result."""

    act: Callable[[str, str, ManagedWorkspace], Awaitable[None]] | None = None
    prompts: dict[str, str] = field(default_factory=dict)

    async def handle(
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: Runner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        # The prompt is one argv element of the production command.
        prompt = "\n".join(claude_cmd)
        self.prompts[todo.phase_id or ""] = prompt
        if self.act is not None:
            await self.act(todo.phase_id or "", prompt, workspace)
        return await super().handle(
            todo,
            workspace,
            agent_env,
            claude_cmd,
            session_id,
            agent_model,
            timeout_seconds,
            collector,
            runner,
            on_launch,
        )


def _wired(
    executions: _Executions, agent: _ReadsItsSetup, world: _World
) -> WorkflowExecutionProcessor:
    processor = _processor(executions, agent)
    # The production prompt and command builders, as `_wiring` passes them.
    processor._prompt_builder = _build_workspace_prompt  # pyright: ignore[reportPrivateUsage]
    processor._command_builder = _build_agent_command  # pyright: ignore[reportPrivateUsage]
    # The production reader, as `_wiring` passes it; only its HTTP is faked.
    processor._remote_branches = world.reader()  # pyright: ignore[reportPrivateUsage]
    return processor


async def _parent_failed_in_implement_after_pushing(
    executions: _Executions, world: _World, *, then_checks_out_main: bool = False
) -> None:
    """research completes; implement pushes B, opens PR N, and fails."""

    async def implement_pushes(phase_id: str, _prompt: str, _workspace: ManagedWorkspace) -> None:
        if phase_id != "implement":
            return
        world.push_and_open_pr()
        if then_checks_out_main:
            world.head = "main"

    agent = _Acts(
        FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE),
            FakeAgentExecutionHandler.failed(exit_code=1),
        ),
        act=implement_pushes,
    )
    result = await _wired(executions, agent, world).run(
        workflow_id=WORKFLOW,
        workflow_name="Continue my branch",
        phases=[_phase(p, i + 1) for i, p in enumerate(PHASE_IDS)],
        inputs={"task": "continue me"},
        execution_id=PARENT,
        repos=[RepositoryRef.from_slug(REPO)],
        source_commits=[SourceCommit(repository=REPO, sha=PINNED)],
    )
    assert result.status == "failed", result


async def _continue_as_told(phase_id: str, prompt: str, workspace: ManagedWorkspace) -> None:
    """The child's implement doing what implement.md says with what its prompt told it.

    Told to continue a branch with an open PR: commit on it and push. Told
    nothing, or that the branch was not continued: start a branch and open a
    PR. Run through the workspace, so the world records exactly what was run.
    """
    if phase_id != "implement":
        return
    await workspace.execute(["git", "-C", DEST, "commit", "-m", "continue #1513"])
    if f"CONTINUE branch `{BRANCH}`" in prompt and "is open from it" in prompt:
        await workspace.execute(["git", "-C", DEST, "push", "origin", f"HEAD:{BRANCH}"])
        return
    await workspace.execute(["git", "-C", DEST, "push", "origin", "HEAD:feat/fresh"])
    await workspace.execute(["gh", "pr", "create", "--draft", "--head", "feat/fresh"])


async def _resumed_child(executions: _Executions, world: _World) -> _Acts:
    parent = await executions.get_by_id(PARENT)
    assert parent is not None
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=PARENT, resume_execution_id=CHILD, acknowledge_external_effects=True
        )
    )
    await executions.save(parent)
    child = _Acts(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE),
        act=_continue_as_told,
    )
    handler = StartResumeHandler(
        _wired(executions, child, world), executions, remote_branches=world.reader()
    )
    await handler.validate(PARENT)
    world.commands.clear()
    result = await handler.handle(PARENT)
    assert result is not None
    assert result.status == "completed", result
    return child


def _parent_failure(executions: _Executions) -> list[object]:
    """The parent's WorkflowFailed.observed_branches, as stored."""
    ((payload,),) = [
        (p,) for m, p in executions.written[PARENT] if m.event_type == "WorkflowFailed"
    ]
    return json.loads(payload)["observed_branches"]


class _StoredStart(BaseModel):
    """The child's start event as stored: its branch facts, and which keys it wrote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    keys: frozenset[str]
    continued_branches: list[ContinuedBranch] | None = None
    abandoned_branches: list[AbandonedBranch] | None = None


def _child_start(executions: _Executions) -> _StoredStart:
    ((_, payload),) = [
        (m, p) for m, p in executions.written[CHILD] if m.event_type == "WorkflowExecutionStarted"
    ]
    stored = WorkflowExecutionStartedEvent.model_validate_json(payload)
    return _StoredStart(
        keys=frozenset(json.loads(payload)),
        continued_branches=stored.continued_branches,
        abandoned_branches=stored.abandoned_branches,
    )


def _branch_checkout(branch: str) -> str:
    return f"git -C {DEST} checkout --quiet -B {branch} refs/remotes/origin/{branch}"


def _pinned_and_fresh(child: _ReadsItsSetup, world: _World) -> None:
    """The child started fresh: implement at the pinned sha, a new branch and PR."""
    lines = child.scripts["implement"].splitlines()
    assert _checkout_line(PINNED) in lines
    assert not any("checkout --quiet -B" in ln for ln in lines)
    assert not [c for c in world.pushes() if f"HEAD:{BRANCH}" in c]


class TestTheParentRecordsItsBranchAndPr:
    async def test_the_failure_records_b_and_its_open_pr_as_facts(self, world: _World) -> None:
        """RED before the fix: the failure held B but no PR, so none was the parent's."""
        executions = _Executions()

        await _parent_failed_in_implement_after_pushing(executions, world)

        (observed,) = _parent_failure(executions)
        assert observed == {
            "repo": "pinned-repo",
            "branch": BRANCH,
            "remote": "origin",
            "remote_commit": PUSHED,
            "remote_commit_at_phase_start": None,
            "unpushed_commits": 0,
            "pull_request": PR,
        }

    async def test_a_branch_switched_away_from_before_failing_is_still_recorded(
        self, world: _World
    ) -> None:
        """RED before the fix: only the checked-out branch was observed."""
        executions = _Executions()

        await _parent_failed_in_implement_after_pushing(
            executions, world, then_checks_out_main=True
        )

        (observed,) = _parent_failure(executions)
        assert observed["branch"] == BRANCH  # type: ignore[index]
        assert observed["pull_request"] == PR  # type: ignore[index]


class TestAResumeContinuesTheBranchItsParentPushed:
    async def test_the_resumed_implement_is_provisioned_on_the_branch_head(
        self, world: _World
    ) -> None:
        """RED before #1513: implement was checked out detached at the pinned sha."""
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions, world)

        child = await _resumed_child(executions, world)

        lines = child.scripts["implement"].splitlines()
        assert _branch_checkout(BRANCH) in lines
        assert _checkout_line(PINNED) not in lines
        # A phase that only reads code keeps the pinned commit.
        assert _checkout_line(PINNED) in child.scripts["review"].splitlines()

    async def test_the_child_pushes_to_b_and_opens_no_second_pr(self, world: _World) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions, world)

        child = await _resumed_child(executions, world)

        # What the agent was launched with, not what the platform meant to say.
        prompt = child.prompts["implement"]
        assert f"CONTINUE branch `{BRANCH}`" in prompt
        assert f"PR #{PR} is open from it" in prompt
        assert "Do NOT open a second PR" in prompt
        assert world.pushes() == [["git", "-C", DEST, "push", "origin", f"HEAD:{BRANCH}"]]
        assert world.opened_prs() == []

    async def test_the_childs_push_advances_the_parents_pr(self, world: _World) -> None:
        """The parent's PR, still the only one open from B, now heads at the child's commit."""
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions, world)
        assert world.open_prs_from(BRANCH) == [(PR, PUSHED)]

        await _resumed_child(executions, world)

        assert world.open_prs_from(BRANCH) == [(PR, CHILD_COMMIT)]
        assert world.opened_prs() == []

    async def test_a_branch_switched_away_from_is_continued_too(self, world: _World) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(
            executions, world, then_checks_out_main=True
        )

        child = await _resumed_child(executions, world)

        assert _branch_checkout(BRANCH) in child.scripts["implement"].splitlines()
        assert world.opened_prs() == []

    async def test_the_continuation_is_a_fact_on_the_childs_start(self, world: _World) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions, world)

        await _resumed_child(executions, world)

        started = _child_start(executions)
        assert started.continued_branches == [
            ContinuedBranch(repository=REPO, branch=BRANCH, head_sha=PUSHED, pull_request=PR)
        ]
        assert "abandoned_branches" not in started.keys
        child = await executions.get_by_id(CHILD)
        assert child is not None
        assert child.start_pins.checkout_for("implement").branches == {REPO: BRANCH}


class TestABranchOrPrThatIsGoneStartsFreshVisibly:
    async def test_a_deleted_branch_is_abandoned_with_its_reason(self, world: _World) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions, world)
        del world.origin[BRANCH]

        child = await _resumed_child(executions, world)

        _pinned_and_fresh(child, world)
        started = _child_start(executions)
        assert "continued_branches" not in started.keys
        (abandoned,) = started.abandoned_branches or []
        assert abandoned.branch == BRANCH
        assert "deleted" in abandoned.reason
        assert f"`{BRANCH}` was NOT continued" in child.prompts["implement"]

    async def test_a_force_pushed_branch_is_not_reused(self, world: _World) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions, world)
        world.origin[BRANCH] = "f" * 40

        child = await _resumed_child(executions, world)

        _pinned_and_fresh(child, world)
        (abandoned,) = _child_start(executions).abandoned_branches or []
        assert "force-pushed or moved" in abandoned.reason

    async def test_the_parents_pr_closed_and_another_opened_is_not_adopted(
        self, world: _World
    ) -> None:
        """RED before the fix: the child continued #OTHER_PR as if it were the parent's."""
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions, world)
        world.close_and_reopen_as_another_pr()

        child = await _resumed_child(executions, world)

        _pinned_and_fresh(child, world)
        started = _child_start(executions)
        assert "continued_branches" not in started.keys
        (abandoned,) = started.abandoned_branches or []
        assert f"#{PR} is no longer open" in abandoned.reason
        assert f"#{OTHER_PR} is open" in abandoned.reason
        assert f"`{BRANCH}` was NOT continued" in child.prompts["implement"]

    async def test_a_forge_nobody_could_ask_is_not_read_as_gone_and_not_trusted(
        self, world: _World
    ) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions, world)
        world.readable = False

        child = await _resumed_child(executions, world)

        _pinned_and_fresh(child, world)
        (abandoned,) = _child_start(executions).abandoned_branches or []
        assert "could not be asked" in abandoned.reason
