"""A resumed phase continues the branch and PR its parent's attempt pushed (#1513).

A v3 implement phase opens a draft PR on its first push. A parent that failed
in implement after that left branch B and PR N behind, and a resume that
started implement fresh opened a second branch and a second PR for one change.

These drive the real chain, faking only what runs git: the parent's failing
phase is observed through `PhaseStartingPoints.observe` (the one place git is
asked where a branch stands), and the forge is a `RemoteBranchPort` double.

    parent's WorkflowFailed.observed_branches, stored as JSON and read back
      -> aggregate's left branches -> `StartResumeCommand` candidates
      -> `StartResumeHandler` asks the forge -> the child's start event
      -> `StartPins.checkout_for` -> provisioning -> `.setup/setup.sh`
      -> `record_continuation` -> the phase's context

Harness shared with #1458, whose pinned-commit chain this extends.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ConfigDict

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    AbandonedBranch,
    ContinuedBranch,
    RemoteBranchReading,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    BranchObservation,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ResumeExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.branch_observation import (
    PhaseStartingPoints,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import ObservedBranches
from syn_domain.contexts.orchestration.slices.execute_workflow.resume_handoff import (
    CONTINUATION_OUTPUT_ID,
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

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
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
PR = 4242


class _Forge:
    """A `RemoteBranchPort` double: answers one reading, records every question."""

    def __init__(self, reading: RemoteBranchReading) -> None:
        self.reading = reading
        self.asked: list[tuple[str, str]] = []

    async def read_branch(self, repository: str, branch: str) -> RemoteBranchReading:
        self.asked.append((repository, branch))
        return self.reading


def _observed_push(phase_id: str | None) -> ObservedBranches | None:
    """What git answers for the parent's implement: it created and pushed BRANCH."""
    if phase_id != "implement":
        return None
    return ObservedBranches(
        branches=(
            BranchObservation(
                repo="pinned-repo",
                branch=BRANCH,
                remote="origin",
                remote_commit=PUSHED,
                remote_commit_at_phase_start=None,
                unpushed_commits=0,
            ),
        )
    )


class _ToldPrompt:
    """Captures the phase outputs each phase's prompt is built with."""

    def __init__(self) -> None:
        self.outputs: dict[str, dict[str, str]] = {}

    async def __call__(
        self,
        phase: ExecutablePhase,
        execution_id: str,
        workflow_id: str,
        repo_url: str | None,
        phase_outputs: dict[str, str],
        inputs: object,
    ) -> str:
        del workflow_id, repo_url, inputs
        self.outputs[f"{execution_id}/{phase.phase_id}"] = dict(phase_outputs)
        return phase.prompt_template


def _with_prompt(
    executions: _Executions, agent: _ReadsItsSetup, told: _ToldPrompt
) -> WorkflowExecutionProcessor:
    processor = _processor(executions, agent)
    processor._prompt_builder = told  # pyright: ignore[reportPrivateUsage]
    return processor


async def _parent_failed_in_implement_after_pushing(executions: _Executions) -> None:
    agent = _ReadsItsSetup(
        FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE),
            FakeAgentExecutionHandler.failed(exit_code=1),
        )
    )

    async def observe(_self: PhaseStartingPoints, phase_id: str | None) -> ObservedBranches | None:
        return _observed_push(phase_id)

    with patch.object(PhaseStartingPoints, "observe", observe):
        result = await _processor(executions, agent).run(
            workflow_id=WORKFLOW,
            workflow_name="Continue my branch",
            phases=[_phase(p, i + 1) for i, p in enumerate(PHASE_IDS)],
            inputs={"task": "continue me"},
            execution_id=PARENT,
            repos=[RepositoryRef.from_slug(REPO)],
            source_commits=[SourceCommit(repository=REPO, sha=PINNED)],
        )
    assert result.status == "failed", result


async def _resumed_child(
    executions: _Executions, forge: _Forge, told: _ToldPrompt
) -> _ReadsItsSetup:
    parent = await executions.get_by_id(PARENT)
    assert parent is not None
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=PARENT, resume_execution_id=CHILD, acknowledge_external_effects=True
        )
    )
    await executions.save(parent)
    child = _ReadsItsSetup(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE))
    handler = StartResumeHandler(
        _with_prompt(executions, child, told), executions, remote_branches=forge
    )
    await handler.validate(PARENT)
    result = await handler.handle(PARENT)
    assert result is not None
    assert result.status == "completed", result
    return child


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


class TestAResumeContinuesTheBranchItsParentPushed:
    async def test_the_resumed_implement_is_provisioned_on_the_branch_head(self) -> None:
        """RED before #1513: implement was checked out detached at the pinned sha."""
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions)
        forge = _Forge(
            RemoteBranchReading(
                repository=REPO,
                branch=BRANCH,
                readable=True,
                head_sha=PUSHED,
                open_pull_request=PR,
            )
        )

        child = await _resumed_child(executions, forge, _ToldPrompt())

        assert forge.asked == [(REPO, BRANCH)]
        lines = child.scripts["implement"].splitlines()
        assert _branch_checkout(BRANCH) in lines
        assert _checkout_line(PINNED) not in lines
        # A phase that only reads code keeps the pinned commit.
        assert _checkout_line(PINNED) in child.scripts["review"].splitlines()

    async def test_the_resumed_implement_is_told_the_branch_and_the_pr(self) -> None:
        """Through the resume handoff, so implement.md's rework path takes it."""
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions)
        forge = _Forge(
            RemoteBranchReading(
                repository=REPO,
                branch=BRANCH,
                readable=True,
                head_sha=PUSHED,
                open_pull_request=PR,
            )
        )
        told = _ToldPrompt()

        await _resumed_child(executions, forge, told)

        handoff = told.outputs[f"{CHILD}/implement"][CONTINUATION_OUTPUT_ID]
        assert f"CONTINUE branch `{BRANCH}`" in handoff
        assert f"PR #{PR} is open from it" in handoff
        assert "Do NOT open a second PR" in handoff

    async def test_the_continuation_is_a_fact_on_the_childs_start(self) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions)
        forge = _Forge(
            RemoteBranchReading(
                repository=REPO,
                branch=BRANCH,
                readable=True,
                head_sha=PUSHED,
                open_pull_request=PR,
            )
        )

        await _resumed_child(executions, forge, _ToldPrompt())

        started = _child_start(executions)
        assert started.continued_branches == [
            ContinuedBranch(repository=REPO, branch=BRANCH, head_sha=PUSHED, pull_request=PR)
        ]
        assert "abandoned_branches" not in started.keys
        child = await executions.get_by_id(CHILD)
        assert child is not None
        assert child.start_pins.checkout_for("implement").branches == {REPO: BRANCH}


class TestABranchThatIsGoneStartsFreshVisibly:
    async def test_a_deleted_branch_is_abandoned_with_its_reason(self) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions)
        forge = _Forge(RemoteBranchReading(repository=REPO, branch=BRANCH, readable=True))
        told = _ToldPrompt()

        child = await _resumed_child(executions, forge, told)

        lines = child.scripts["implement"].splitlines()
        assert _checkout_line(PINNED) in lines
        assert not any("checkout --quiet -B" in ln for ln in lines)
        started = _child_start(executions)
        assert "continued_branches" not in started.keys
        (abandoned,) = started.abandoned_branches or []
        assert abandoned.branch == BRANCH
        assert "deleted" in abandoned.reason
        handoff = told.outputs[f"{CHILD}/implement"][CONTINUATION_OUTPUT_ID]
        assert f"`{BRANCH}` was NOT continued" in handoff

    async def test_a_force_pushed_branch_is_not_reused(self) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions)
        forge = _Forge(
            RemoteBranchReading(
                repository=REPO,
                branch=BRANCH,
                readable=True,
                head_sha="f" * 40,
                open_pull_request=PR,
            )
        )

        child = await _resumed_child(executions, forge, _ToldPrompt())

        assert _checkout_line(PINNED) in child.scripts["implement"].splitlines()
        (abandoned,) = _child_start(executions).abandoned_branches or []
        assert "force-pushed or moved" in abandoned.reason

    async def test_a_forge_nobody_could_ask_is_not_read_as_gone_and_not_trusted(self) -> None:
        executions = _Executions()
        await _parent_failed_in_implement_after_pushing(executions)
        forge = _Forge(RemoteBranchReading(repository=REPO, branch=BRANCH, readable=False))

        child = await _resumed_child(executions, forge, _ToldPrompt())

        assert _checkout_line(PINNED) in child.scripts["implement"].splitlines()
        (abandoned,) = _child_start(executions).abandoned_branches or []
        assert "could not be asked" in abandoned.reason
