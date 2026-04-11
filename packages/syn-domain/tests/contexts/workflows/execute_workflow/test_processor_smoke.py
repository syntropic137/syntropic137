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


def _make_processor(agent_handler: FakeAgentExecutionHandler) -> WorkflowExecutionProcessor:
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
    )


def _one_phase_workflow() -> list[ExecutablePhase]:
    return [
        ExecutablePhase(
            phase_id="phase-001",
            name="Smoke Phase",
            order=1,
            description="Single phase for smoke testing",
            agent_config=AgentConfiguration(),
            prompt_template="do the thing",
            output_artifact_type="text",
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
