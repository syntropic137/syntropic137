"""A forked child runs from its resume phase, from the parent's pins (#1454).

These drive the REAL processor end to end twice over the same repository:
once as the parent, which completes `research` and fails in `plan`, and once
as the child its fork admitted. Only the agent, the artifact query and the
prompt builder are doubles, and each is there to be asked a question:

* the agent - which phases were run at all;
* the prompt builder - what each phase was provisioned with;
* the artifact query - where the inherited outputs were read from.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import pytest
from event_sourcing import StreamAlreadyExistsError

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.artifacts import ArtifactSummary, PhaseOutputFile
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ForkExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.start_fork import StartForkHandler
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler
from syn_domain.testing.fake_session_repository import FakeSessionRepository

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

pytestmark = pytest.mark.unit

PARENT = "exec-fork-parent"
FORK = "exec-fork-child"
WORKFLOW = "wf-fork"
PHASE_IDS = ("research", "plan", "implement")

#: What the parent's stored research artifact reads as, through the query.
#: Nothing else in these runs produces this string: the fake agent writes a
#: different one, so seeing it in the child's prompt means it came from the
#: PARENT's artifacts and not from anything the child ran.
PARENT_RESEARCH = "research the parent kept"


def _phase(phase_id: str, order: int, prompt: str) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id=phase_id,
        name=phase_id.title(),
        order=order,
        agent_config=AgentConfiguration(),
        prompt_template=prompt,
        output_artifact_types=(),
        timeout_seconds=1800,
    )


def _pinned() -> list[ExecutablePhase]:
    """The phase config the parent started with."""
    return [_phase(p, i + 1, f"{p} as pinned") for i, p in enumerate(PHASE_IDS)]


def _edited() -> list[ExecutablePhase]:
    """The same workflow after someone edited it: every prompt rewritten,
    `plan` renamed away and a new phase put in front of `implement`."""
    return [
        _phase("research", 1, "research as edited"),
        _phase("plan-v2", 2, "plan as edited"),
        _phase("review", 3, "review as edited"),
        _phase("implement", 4, "implement as edited"),
    ]


class _Executions:
    """One store of execution streams, shared by the parent's run and the child's."""

    def __init__(self) -> None:
        self.streams: dict[str, WorkflowExecutionAggregate] = {}

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.streams[aggregate.id or ""] = aggregate
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        if aggregate.id in self.streams:
            raise StreamAlreadyExistsError(aggregate.id or "", 0)
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return self.streams.get(aggregate_id)


class _NoArtifacts:
    async def save(self, aggregate: object) -> None:
        del aggregate

    async def get_by_id(self, aggregate_id: str) -> None:
        del aggregate_id


@dataclass
class _ArtifactQuery:
    """Answers only the one question a fork asks, and remembers it was asked."""

    asked: list[tuple[str, dict[str, list[str]]]] = field(default_factory=list)

    async def get_for_phase_injection(
        self, execution_id: str, completed_phase_ids: list[str]
    ) -> dict[str, str]:
        del execution_id, completed_phase_ids
        return {}

    async def get_files_for_phase_injection(
        self, execution_id: str, completed_phase_ids: list[str]
    ) -> dict[str, list[PhaseOutputFile]]:
        del execution_id, completed_phase_ids
        return {}

    async def get_files_for_artifacts(
        self, execution_id: str, phase_artifact_ids: Mapping[str, Sequence[str]]
    ) -> dict[str, list[PhaseOutputFile]]:
        self.asked.append((execution_id, {k: list(v) for k, v in phase_artifact_ids.items()}))
        return {
            phase_id: [PhaseOutputFile(source_path=None, content=PARENT_RESEARCH)]
            for phase_id in phase_artifact_ids
        }

    async def get_by_execution(self, execution_id: str) -> list[ArtifactSummary]:
        del execution_id
        return []


@dataclass
class _Provisioned:
    """Each phase the processor built a prompt for, with what it was given."""

    prompts: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, dict[str, str]] = field(default_factory=dict)

    async def build(
        self,
        phase: ExecutablePhase,
        execution_id: str,
        workflow_id: str,
        repo_url: str | None,
        phase_outputs: dict[str, str],
        inputs: dict[str, object],
    ) -> str:
        del execution_id, workflow_id, repo_url, inputs
        self.prompts[phase.phase_id] = phase.prompt_template
        self.outputs[phase.phase_id] = dict(phase_outputs)
        return phase.prompt_template


def _command(phase: ExecutablePhase, prompt: str) -> list[str]:
    del phase
    return ["echo", prompt]


def _processor(
    executions: _Executions,
    agent: FakeAgentExecutionHandler,
    provisioned: _Provisioned,
    query: _ArtifactQuery | None = None,
) -> WorkflowExecutionProcessor:
    return WorkflowExecutionProcessor(
        execution_repository=executions,
        session_repository=FakeSessionRepository(),
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=_NoArtifacts(),
        artifact_content_storage=None,
        artifact_query=query,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=provisioned.build,
        command_builder=_command,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=agent,
    )


def _ran(agent: FakeAgentExecutionHandler) -> list[str]:
    return [todo.phase_id or "" for todo in agent.calls]


async def _failed_in_plan(executions: _Executions) -> None:
    """The parent: research completes, plan fails, implement never starts."""
    agent = FakeAgentExecutionHandler.scripted(
        FakeAgentExecutionHandler.success(
            produces=[("artifacts/output/findings.md", b"research the agent wrote")]
        ),
        FakeAgentExecutionHandler.failed(exit_code=1),
    )
    result = await _processor(executions, agent, _Provisioned()).run(
        workflow_id=WORKFLOW,
        workflow_name="Fork me",
        phases=_pinned(),
        inputs={"task": "fork me"},
        execution_id=PARENT,
    )
    assert result.status == "failed", result
    assert _ran(agent) == ["research", "plan"]


async def _forked(executions: _Executions) -> WorkflowExecutionAggregate:
    await _failed_in_plan(executions)
    parent = executions.streams[PARENT]
    parent.fork_execution(
        ForkExecutionCommand(
            execution_id=PARENT, fork_execution_id=FORK, acknowledge_external_effects=True
        )
    )
    await executions.save(parent)
    return parent


async def _start_child(
    executions: _Executions,
) -> tuple[FakeAgentExecutionHandler, _Provisioned, _ArtifactQuery]:
    agent = FakeAgentExecutionHandler.success()
    provisioned = _Provisioned()
    query = _ArtifactQuery()
    handler = StartForkHandler(_processor(executions, agent, provisioned, query), executions)
    result = await handler.handle(PARENT)
    assert result is not None
    assert result.status == "completed", result
    return agent, provisioned, query


class TestTheChildDoesNotRerunWhatItInherited:
    async def test_it_runs_from_the_failed_phase_on(self) -> None:
        executions = _Executions()
        await _forked(executions)

        agent, provisioned, _ = await _start_child(executions)

        assert _ran(agent) == ["plan", "implement"]
        assert "research" not in provisioned.prompts

    async def test_the_inherited_phase_is_closed_on_the_child(self) -> None:
        """Not only skipped by this drain: no later command may start it."""
        executions = _Executions()
        parent = await _forked(executions)
        child = WorkflowExecutionAggregate()
        child.start_fork(parent.fork_start_command())
        assert child.status is ExecutionStatus.RUNNING

        with pytest.raises(ValueError, match="research: it has already completed"):
            child.start_phase(
                StartPhaseCommand(
                    execution_id=FORK,
                    workflow_id=WORKFLOW,
                    phase_id="research",
                    phase_name="Research",
                    phase_order=1,
                )
            )

    async def test_the_resumed_phase_reads_the_parents_research(self) -> None:
        executions = _Executions()
        parent = await _forked(executions)
        (research,) = parent.fork_start_command().forked_from.inherited_phases
        assert research.artifact_ids, "the parent's research must have kept an artifact"

        _, provisioned, query = await _start_child(executions)

        assert query.asked == [(PARENT, {"research": research.artifact_ids})]
        assert provisioned.outputs["plan"]["research"] == PARENT_RESEARCH

    async def test_the_parent_and_child_name_each_other(self) -> None:
        executions = _Executions()
        await _forked(executions)
        await _start_child(executions)

        parent, child = executions.streams[PARENT], executions.streams[FORK]
        assert parent.fork_execution_id == FORK
        origin = child.start_pins.forked_from
        assert origin is not None
        assert origin.parent_execution_id == PARENT
        assert [p.phase_id for p in origin.inherited_phases] == ["research"]
        assert origin.resume_phase_id == "plan"
        assert parent.status is ExecutionStatus.FAILED
        assert child.status is ExecutionStatus.COMPLETED

    async def test_a_second_start_starts_nothing(self) -> None:
        executions = _Executions()
        await _forked(executions)
        await _start_child(executions)

        again = FakeAgentExecutionHandler.success()
        handler = StartForkHandler(_processor(executions, again, _Provisioned()), executions)

        assert await handler.handle(PARENT) is None
        assert again.call_count == 0


class TestAStaleWorkflowEditCannotChangeWhatTheChildRuns:
    async def test_the_child_runs_the_pinned_prompts_not_the_edited_ones(self) -> None:
        """The workflow is edited between the parent's start and the fork.

        The fork path has no way to read the template at all - the handler is
        built from the execution repository alone - so the edit below is held
        by nothing the child can see. What this pins is the positive half: the
        prompts that ran are the ones the PARENT started with, which only its
        start event carries. Before #1454 that event held ids, names and
        orders; a child built from it had no prompt to run but the template's.
        """
        executions = _Executions()
        await _forked(executions)
        edited = _edited()

        _, provisioned, _ = await _start_child(executions)

        assert provisioned.prompts == {
            "plan": "plan as pinned",
            "implement": "implement as pinned",
        }
        assert not set(provisioned.prompts.values()) & {p.prompt_template for p in edited}

    async def test_mutating_the_list_the_parent_started_with_changes_nothing(self) -> None:
        """The snapshot is the parent's event, not a reference to the caller's list."""
        executions = _Executions()
        phases = _pinned()
        agent = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.success(),
            FakeAgentExecutionHandler.failed(exit_code=1),
        )
        await _processor(executions, agent, _Provisioned()).run(
            workflow_id=WORKFLOW,
            workflow_name="Fork me",
            phases=phases,
            inputs={},
            execution_id=PARENT,
        )
        phases[1] = replace(phases[1], prompt_template="plan as edited")
        parent = executions.streams[PARENT]
        parent.fork_execution(
            ForkExecutionCommand(
                execution_id=PARENT, fork_execution_id=FORK, acknowledge_external_effects=True
            )
        )

        pinned = {p.phase_id: p.prompt_template for p in parent.fork_start_command().pinned_phases}

        assert pinned["plan"] == "plan as pinned"
