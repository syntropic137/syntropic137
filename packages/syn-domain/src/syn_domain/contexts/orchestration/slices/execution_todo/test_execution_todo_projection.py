"""Unit tests for ExecutionTodoProjection (ISS-196).

Tests the to-do list read model that drives the Processor To-Do List pattern.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.execution_todo.value_objects import (
    TodoAction,
)

# =========================================================================
# Test data
# =========================================================================

TWO_PHASE_STARTED_EVENT = {
    "execution_id": "exec-1",
    "workflow_id": "wf-1",
    "workflow_name": "Test",
    "total_phases": 2,
    "started_at": "2026-03-10T00:00:00Z",
    "inputs": {},
    "phase_definitions": [
        {"phase_id": "p-1", "name": "Research", "order": 1, "timeout_seconds": 300},
        {"phase_id": "p-2", "name": "Implement", "order": 2, "timeout_seconds": 300},
    ],
}

LEGACY_STARTED_EVENT = {
    "execution_id": "exec-legacy",
    "workflow_id": "wf-1",
    "workflow_name": "Legacy",
    "total_phases": 1,
    "started_at": "2026-03-10T00:00:00Z",
    "inputs": {},
    # No phase_definitions — legacy mode
}


# =========================================================================
# Full lifecycle test
# =========================================================================


@pytest.mark.unit
class TestFullLifecycle:
    """Test complete multi-phase workflow produces correct todo sequence."""

    @pytest.mark.anyio
    async def test_two_phase_lifecycle(self) -> None:
        """Full lifecycle: 2-phase workflow produces correct todo sequence."""
        proj = ExecutionTodoProjection()

        # 1. Execution started → PROVISION_WORKSPACE for phase 1
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        todos = proj.get_pending("exec-1")
        assert len(todos) == 1
        assert todos[0].action == TodoAction.PROVISION_WORKSPACE
        assert todos[0].phase_id == "p-1"

        # 2. Workspace provisioned → RUN_AGENT
        await proj.on_workspace_provisioned_for_phase(
            {"execution_id": "exec-1", "phase_id": "p-1", "workspace_id": "ws-1"}
        )
        todos = proj.get_pending("exec-1")
        assert len(todos) == 1
        assert todos[0].action == TodoAction.RUN_AGENT
        assert todos[0].workspace_id == "ws-1"

        # 3. Agent completed → COLLECT_ARTIFACTS
        await proj.on_agent_execution_completed(
            {"execution_id": "exec-1", "phase_id": "p-1", "session_id": "sess-1"}
        )
        todos = proj.get_pending("exec-1")
        assert len(todos) == 1
        assert todos[0].action == TodoAction.COLLECT_ARTIFACTS
        assert todos[0].session_id == "sess-1"

        # 4. Artifacts collected → COMPLETE_PHASE
        await proj.on_artifacts_collected_for_phase(
            {"execution_id": "exec-1", "phase_id": "p-1", "artifact_ids": ["art-1"]}
        )
        todos = proj.get_pending("exec-1")
        assert len(todos) == 1
        assert todos[0].action == TodoAction.COMPLETE_PHASE

        # 5. Phase completed → cleared
        await proj.on_phase_completed({"execution_id": "exec-1", "phase_id": "p-1"})
        todos = proj.get_pending("exec-1")
        assert len(todos) == 0

        # 6. Next phase ready → PROVISION_WORKSPACE for phase 2
        await proj.on_next_phase_ready(
            {"execution_id": "exec-1", "next_phase_id": "p-2", "next_phase_order": 2}
        )
        todos = proj.get_pending("exec-1")
        assert len(todos) == 1
        assert todos[0].action == TodoAction.PROVISION_WORKSPACE
        assert todos[0].phase_id == "p-2"

        # 7-10. Second phase goes through same lifecycle
        await proj.on_workspace_provisioned_for_phase(
            {"execution_id": "exec-1", "phase_id": "p-2", "workspace_id": "ws-2"}
        )
        await proj.on_agent_execution_completed(
            {"execution_id": "exec-1", "phase_id": "p-2", "session_id": "sess-2"}
        )
        await proj.on_artifacts_collected_for_phase(
            {"execution_id": "exec-1", "phase_id": "p-2", "artifact_ids": ["art-2"]}
        )
        await proj.on_phase_completed({"execution_id": "exec-1", "phase_id": "p-2"})
        todos = proj.get_pending("exec-1")
        assert len(todos) == 0

        # 11. Workflow completed → all cleared
        await proj.on_workflow_completed({"execution_id": "exec-1"})
        assert proj.get_pending("exec-1") == []


# =========================================================================
# Terminal events clear all todos
# =========================================================================


@pytest.mark.unit
class TestTerminalEventsClearTodos:
    """Terminal events should clear all pending todos."""

    @pytest.mark.anyio
    async def test_workflow_failed_clears(self) -> None:
        """WorkflowFailed clears all todos."""
        proj = ExecutionTodoProjection()
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        assert len(proj.get_pending("exec-1")) == 1

        await proj.on_workflow_failed({"execution_id": "exec-1"})
        assert proj.get_pending("exec-1") == []

    @pytest.mark.anyio
    async def test_execution_cancelled_clears(self) -> None:
        """ExecutionCancelled clears all todos."""
        proj = ExecutionTodoProjection()
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        await proj.on_execution_cancelled({"execution_id": "exec-1"})
        assert proj.get_pending("exec-1") == []

    @pytest.mark.anyio
    async def test_workflow_interrupted_clears(self) -> None:
        """WorkflowInterrupted clears all todos."""
        proj = ExecutionTodoProjection()
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        await proj.on_workflow_interrupted({"execution_id": "exec-1"})
        assert proj.get_pending("exec-1") == []


# =========================================================================
# Legacy mode
# =========================================================================


@pytest.mark.unit
class TestLegacyMode:
    """Without phase_definitions, projection is no-op."""

    @pytest.mark.anyio
    async def test_no_phase_definitions_no_todos(self) -> None:
        """Legacy mode: no phase_definitions → no todos created."""
        proj = ExecutionTodoProjection()
        await proj.on_workflow_execution_started(LEGACY_STARTED_EVENT)
        assert proj.get_pending("exec-legacy") == []


# =========================================================================
# Edge cases
# =========================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.anyio
    async def test_empty_execution_id_ignored(self) -> None:
        """Events with empty execution_id are ignored."""
        proj = ExecutionTodoProjection()
        await proj.on_workflow_execution_started({"execution_id": "", "phase_definitions": []})
        assert proj._todos == {}

    @pytest.mark.anyio
    async def test_get_pending_unknown_execution(self) -> None:
        """get_pending for unknown execution returns empty list."""
        proj = ExecutionTodoProjection()
        assert proj.get_pending("nonexistent") == []

    @pytest.mark.anyio
    async def test_clear_all_data(self) -> None:
        """clear_all_data removes all state."""
        proj = ExecutionTodoProjection()
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        assert len(proj.get_pending("exec-1")) == 1

        await proj.clear_all_data()
        assert proj.get_pending("exec-1") == []

    @pytest.mark.anyio
    async def test_phases_sorted_by_order(self) -> None:
        """First phase is determined by order, not list position."""
        event = {
            **TWO_PHASE_STARTED_EVENT,
            "phase_definitions": [
                {"phase_id": "p-2", "name": "Second", "order": 2},
                {"phase_id": "p-1", "name": "First", "order": 1},
            ],
        }
        proj = ExecutionTodoProjection()
        await proj.on_workflow_execution_started(event)
        todos = proj.get_pending("exec-1")
        assert todos[0].phase_id == "p-1"
