"""Processor-level smoke tests for WorkflowExecutionProcessor.run().

These tests exercise the FULL run() loop — workspace provisioning, agent execution,
projection sync, and todo-list drain — using only in-memory infrastructure. No Docker,
no network, no real event store required.

Why these tests matter
----------------------
The cancel-path bug fixed in #663 was caught by Copilot code review, not tests.
``test_cancel_returns_cancelled`` would have caught it: when ``run()`` returns
``status="failed"`` instead of ``"cancelled"``, the assertion fails immediately.

Sync-safety
-----------
``FakeAgentExecutionHandler`` is checked against ``AgentHandlerProtocol`` at import
time via a module-level type assertion. If ``AgentExecutionHandler.handle()`` changes
its signature, pyright fails here on the next CI run — no silent drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )


# ---------------------------------------------------------------------------
# In-memory fake repositories
# ---------------------------------------------------------------------------


class FakeExecutionRepository:
    """Minimal in-memory execution repository for smoke tests.

    Clears ``_uncommitted_events`` after save, mirroring what the real SDK
    repository does — required for ``_save_and_sync`` to not re-process events
    on subsequent saves.
    """

    def __init__(self) -> None:
        self._aggregates: dict[str, WorkflowExecutionAggregate] = {}

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self._aggregates[aggregate.id] = aggregate
        aggregate._uncommitted_events.clear()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        if aggregate.id in self._aggregates:
            from event_sourcing import StreamAlreadyExistsError

            raise StreamAlreadyExistsError(aggregate.id, 0)
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return self._aggregates.get(aggregate_id)


class FakeSessionRepository:
    """Minimal in-memory session repository (save-only) for smoke tests."""

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        pass  # No-op — smoke tests don't assert on session state


class FakeArtifactRepository:
    """Minimal in-memory artifact repository for smoke tests."""

    async def save(self, aggregate: object) -> None:
        pass

    async def get_by_id(self, aggregate_id: str) -> None:
        return None


# ---------------------------------------------------------------------------
# Shared builder
# ---------------------------------------------------------------------------


async def _noop_prompt_builder(
    phase: ExecutablePhase,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
    phase_outputs: dict,
    inputs: dict,
) -> str:
    return "smoke test prompt"


def _noop_command_builder(phase: ExecutablePhase, prompt: str) -> list[str]:
    return ["echo", "smoke-test-agent"]


def _make_processor(
    agent_handler: FakeAgentExecutionHandler,
    session_capture: object | None = None,
) -> WorkflowExecutionProcessor:
    """Wire a WorkflowExecutionProcessor with all in-memory/fake dependencies."""
    todo_store = InMemoryProjectionStore()
    todo_projection = ExecutionTodoProjection(store=todo_store)

    return WorkflowExecutionProcessor(
        execution_repository=FakeExecutionRepository(),
        session_repository=FakeSessionRepository(),
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=FakeArtifactRepository(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=_noop_prompt_builder,
        command_builder=_noop_command_builder,
        todo_projection=todo_projection,
        agent_handler=agent_handler,
        session_capture=session_capture,  # type: ignore[arg-type]
    )


def _one_phase_workflow() -> list[ExecutablePhase]:
    """One phase that declares NO output, matching a fake agent that writes none.

    The empty declaration is deliberate. These tests drive the real collection
    step with an agent double that produces no files, so declaring an output
    type here would (correctly, since #1167) fail every one of them for a
    reason none of them is about.
    """
    return [
        ExecutablePhase(
            phase_id="phase-001",
            name="Smoke Phase",
            order=1,
            description="Single phase for smoke testing",
            agent_config=AgentConfiguration(),
            prompt_template="do the thing",
            output_artifact_types=(),
            timeout_seconds=30,
        )
    ]


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessorSmoke:
    """Full run() loop smoke tests — in-memory only, no Docker."""

    async def test_cancel_returns_cancelled(self) -> None:
        """Cancel signal must propagate through run() as status='cancelled'.

        Regression guard for the bug caught in #663 Copilot review: when the
        agent emits interrupt_requested=True, the processor was incorrectly
        routing through _fail_execution(), returning status='failed'.
        """
        fake = FakeAgentExecutionHandler.cancelled()
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-smoke-001",
            workflow_name="Smoke Test Workflow",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-smoke-cancel-001",
        )

        assert result.status == "cancelled", (
            f"Expected 'cancelled' but got '{result.status}'. "
            "The cancel signal is being swallowed — check _handle_run_agent and _cancel_execution."
        )
        assert fake.call_count == 1, "Agent handler should have been reached exactly once"

    async def test_cancel_with_NO_reason_returns_cancelled(self) -> None:
        """#918: a cancel carrying no reason must still cancel, end to end.

        The test above passes a reason, and so did the fake until now. That is
        precisely why #918 survived: `interrupt_requested` was derived as
        `interrupt_reason is not None`, so every test that supplied a reason
        stayed green while the real CLI path - `syn control cancel --force`
        with no `-r` - was silently ignored and the workflow ran on.

        This drives the whole processor rather than stopping at StreamResult,
        so it guards the downstream default in WorkflowExecutionProcessor too.
        """
        fake = FakeAgentExecutionHandler.cancelled(reason=None)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-smoke-003",
            workflow_name="Smoke Test Workflow",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-smoke-cancel-noreason",
        )

        assert result.status == "cancelled", (
            f"Expected 'cancelled' but got '{result.status}'. A cancel with no "
            "reason text is still a cancel (#918); deriving the interrupt flag "
            "from an optional message is what let this run to completion."
        )
        assert fake.call_count == 1

    async def test_failure_returns_failed(self) -> None:
        """Non-zero exit code with no cancel signal must return status='failed'."""
        fake = FakeAgentExecutionHandler.failed(exit_code=1)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-smoke-002",
            workflow_name="Smoke Test Workflow",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-smoke-fail-001",
        )

        assert result.status == "failed", f"Expected 'failed' but got '{result.status}'."
        assert fake.call_count == 1

    async def test_success_returns_completed(self) -> None:
        """Clean exit code 0 must return status='completed'."""
        fake = FakeAgentExecutionHandler.success()
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-smoke-003",
            workflow_name="Smoke Test Workflow",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-smoke-success-001",
        )

        assert result.status == "completed", f"Expected 'completed' but got '{result.status}'."
        assert fake.call_count == 1


def _two_phase_workflow(
    first_declares: tuple[str, ...],
    second_declares: tuple[str, ...] = (),
) -> list[ExecutablePhase]:
    """Two sequential phases, so "the next one did not run" is observable.

    A single-phase workflow cannot express the property that matters in #1167:
    the failure was not that a phase produced nothing, it was that the run
    CARRIED ON without it. When the vanished phase is `verify`, carrying on is
    the whole defect.
    """
    return [
        ExecutablePhase(
            phase_id="phase-001",
            name="Produce Phase",
            order=1,
            description="Declares output",
            agent_config=AgentConfiguration(),
            prompt_template="produce the thing",
            output_artifact_types=first_declares,
            timeout_seconds=30,
        ),
        ExecutablePhase(
            phase_id="phase-002",
            name="Downstream Phase",
            order=2,
            description="Must not run if phase 1 failed its contract",
            agent_config=AgentConfiguration(),
            prompt_template="consume the thing",
            output_artifact_types=second_declares,
            timeout_seconds=30,
        ),
    ]


@pytest.mark.unit
class TestADeclaredOutputMustBeProduced:
    """#1167: a phase that promises output and delivers none fails the run.

    Four real executions ended `status=completed, error_message=None,
    artifact_id=None` - the phase produced none of the output its contract
    declared and the execution advanced regardless. In one of them the phase
    was `verify`, so the review gate left the run silently while every surface
    still reported success.

    These drive the FULL processor loop rather than the collector alone,
    because the defect was never in one object: the declaration was collapsed
    to a scalar four hops upstream, and each end of every hop looked correct.
    """

    async def test_declared_but_unproduced_fails_and_stops_the_run(self) -> None:
        """(a) The gate cannot be skipped: phase 2 must not run.

        `call_count == 1` is the assertion that matters. A version of this fix
        that failed the phase but let the execution continue would still
        report `status='failed'` here while leaving the real defect - a
        removed gate that nobody notices - completely intact.
        """
        fake = FakeAgentExecutionHandler.success()  # exit 0, writes nothing
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1167-missing",
            workflow_name="Missing Artifact Workflow",
            phases=_two_phase_workflow(first_declares=("plan",)),
            inputs={},
            execution_id="exec-1167-missing",
        )

        assert result.status == "failed", (
            f"Expected 'failed' but got '{result.status}'. A phase declaring "
            "'plan' and writing nothing under artifacts/output/ produced none "
            "of its contract; completing it is #1167."
        )
        assert result.error_message is not None
        assert "phase-001" in result.error_message, (
            f"The error must NAME the phase that broke its contract, got: {result.error_message!r}"
        )
        assert "plan" in result.error_message, (
            f"The error must name WHAT was missing, got: {result.error_message!r}"
        )
        assert fake.call_count == 1, (
            f"The downstream phase ran anyway ({fake.call_count} agent calls). "
            "Failing the phase while letting the execution advance leaves the "
            "defect intact - a dropped `verify` still disappears from the run."
        )

    async def test_a_phase_declaring_nothing_may_produce_nothing(self) -> None:
        """(b) The true negative. Without this the fix breaks legitimate phases.

        Four phases in the shipped self-host validation workflows declare no
        `output_artifacts` (`delegation:build-and-delegate`,
        `github-ops:exercise`, `skills-injection:report` and `:confirm`). They
        answer a question and stop, nothing downstream reads them, and they
        must keep passing. Only a DECLARED-and-unproduced output is a failure.
        """
        fake = FakeAgentExecutionHandler.success()  # writes nothing, as above
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1167-undeclared",
            workflow_name="Undeclared Output Workflow",
            phases=_two_phase_workflow(first_declares=()),
            inputs={},
            execution_id="exec-1167-undeclared",
        )

        assert result.status == "completed", (
            f"Expected 'completed' but got '{result.status}' "
            f"({result.error_message!r}). A phase that declares no output "
            "artifact types is allowed to produce none; failing it would break "
            "every shipped validation workflow."
        )
        assert fake.call_count == 2, "Both phases should have run to completion"

    async def test_a_phase_that_produces_what_it_declared_is_unaffected(self) -> None:
        """(c) The happy path still completes, and the artifact still lands.

        Asserting only the status would pass even if the enforcement had eaten
        the artifact on its way through, so the collected id is checked too -
        that is the hop the plural declaration now travels.
        """
        fake = FakeAgentExecutionHandler.success(
            produces=[("artifacts/output/deliverable.md", b"# Real output")]
        )
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1167-produced",
            workflow_name="Produced Output Workflow",
            phases=_two_phase_workflow(first_declares=("plan",), second_declares=("markdown",)),
            inputs={},
            execution_id="exec-1167-produced",
        )

        assert result.status == "completed", (
            f"Expected 'completed' but got '{result.status}' "
            f"({result.error_message!r}). Both phases declared output and both "
            "wrote a file, so nothing here should trip the #1167 gate."
        )
        assert fake.call_count == 2
        assert len(result.artifact_ids) == 2, (
            f"Expected one artifact per phase, got {result.artifact_ids}. The "
            "declaration now travels as a tuple; a hop that dropped it would "
            "surface here as a lost artifact."
        )
