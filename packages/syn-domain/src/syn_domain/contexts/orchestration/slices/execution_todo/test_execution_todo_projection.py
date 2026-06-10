"""Unit tests for ExecutionTodoProjection (ISS-196).

Tests the to-do list read model that drives the Processor To-Do List pattern.
"""

from __future__ import annotations

import asyncio

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    _ACTION_RANK,
    _RANK_PHASE_DONE,
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
        proj = ExecutionTodoProjection(store=InMemoryProjectionStore())

        # 1. Execution started → PROVISION_WORKSPACE for phase 1
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        todos = await proj.get_pending("exec-1")
        assert len(todos) == 1
        assert todos[0].action == TodoAction.PROVISION_WORKSPACE
        assert todos[0].phase_id == "p-1"

        # 2. Workspace provisioned → RUN_AGENT
        await proj.on_workspace_provisioned_for_phase(
            {"execution_id": "exec-1", "phase_id": "p-1", "workspace_id": "ws-1"}
        )
        todos = await proj.get_pending("exec-1")
        assert len(todos) == 1
        assert todos[0].action == TodoAction.RUN_AGENT
        assert todos[0].workspace_id == "ws-1"

        # 3. Agent completed → COLLECT_ARTIFACTS
        await proj.on_agent_execution_completed(
            {"execution_id": "exec-1", "phase_id": "p-1", "session_id": "sess-1"}
        )
        todos = await proj.get_pending("exec-1")
        assert len(todos) == 1
        assert todos[0].action == TodoAction.COLLECT_ARTIFACTS
        assert todos[0].session_id == "sess-1"

        # 4. Artifacts collected → COMPLETE_PHASE
        await proj.on_artifacts_collected_for_phase(
            {"execution_id": "exec-1", "phase_id": "p-1", "artifact_ids": ["art-1"]}
        )
        todos = await proj.get_pending("exec-1")
        assert len(todos) == 1
        assert todos[0].action == TodoAction.COMPLETE_PHASE

        # 5. Phase completed → cleared
        await proj.on_phase_completed({"execution_id": "exec-1", "phase_id": "p-1"})
        todos = await proj.get_pending("exec-1")
        assert len(todos) == 0

        # 6. Next phase ready → PROVISION_WORKSPACE for phase 2
        await proj.on_next_phase_ready(
            {"execution_id": "exec-1", "next_phase_id": "p-2", "next_phase_order": 2}
        )
        todos = await proj.get_pending("exec-1")
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
        todos = await proj.get_pending("exec-1")
        assert len(todos) == 0

        # 11. Workflow completed → all cleared
        await proj.on_workflow_completed({"execution_id": "exec-1"})
        assert await proj.get_pending("exec-1") == []


# =========================================================================
# Terminal events clear all todos
# =========================================================================


@pytest.mark.unit
class TestTerminalEventsClearTodos:
    """Terminal events should clear all pending todos."""

    @pytest.mark.anyio
    async def test_workflow_failed_clears(self) -> None:
        """WorkflowFailed clears all todos."""
        proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        assert len(await proj.get_pending("exec-1")) == 1

        await proj.on_workflow_failed({"execution_id": "exec-1"})
        assert await proj.get_pending("exec-1") == []

    @pytest.mark.anyio
    async def test_execution_cancelled_clears(self) -> None:
        """ExecutionCancelled clears all todos."""
        proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        await proj.on_execution_cancelled({"execution_id": "exec-1"})
        assert await proj.get_pending("exec-1") == []

    @pytest.mark.anyio
    async def test_workflow_interrupted_clears(self) -> None:
        """WorkflowInterrupted clears all todos."""
        proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        await proj.on_workflow_interrupted({"execution_id": "exec-1"})
        assert await proj.get_pending("exec-1") == []


# =========================================================================
# Legacy mode
# =========================================================================


@pytest.mark.unit
class TestLegacyMode:
    """Without phase_definitions, projection is no-op."""

    @pytest.mark.anyio
    async def test_no_phase_definitions_no_todos(self) -> None:
        """Legacy mode: no phase_definitions → no todos created."""
        proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
        await proj.on_workflow_execution_started(LEGACY_STARTED_EVENT)
        assert await proj.get_pending("exec-legacy") == []


# =========================================================================
# Edge cases
# =========================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.anyio
    async def test_empty_execution_id_ignored(self) -> None:
        """Events with empty execution_id are ignored."""
        proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
        await proj.on_workflow_execution_started({"execution_id": "", "phase_definitions": []})
        assert await proj.get_pending("") == []

    @pytest.mark.anyio
    async def test_get_pending_unknown_execution(self) -> None:
        """get_pending for unknown execution returns empty list."""
        proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
        assert await proj.get_pending("nonexistent") == []

    @pytest.mark.anyio
    async def test_clear_all_data(self) -> None:
        """clear_all_data removes all state."""
        proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
        await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        assert len(await proj.get_pending("exec-1")) == 1

        await proj.clear_all_data()
        assert await proj.get_pending("exec-1") == []

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
        proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
        await proj.on_workflow_execution_started(event)
        todos = await proj.get_pending("exec-1")
        assert todos[0].phase_id == "p-1"


# =========================================================================
# Monotonic race guards (D1 fix hardening)
# =========================================================================


class _YieldingStore(InMemoryProjectionStore):
    """InMemory store whose get/save yield to the event loop.

    Forces real interleaving between concurrent writers so the
    per-execution lock + monotonic merge are exercised, not just the
    happy sequential path.
    """

    async def get(self, projection: str, key: str) -> dict | None:
        await asyncio.sleep(0)
        return await super().get(projection, key)

    async def save(self, projection: str, key: str, data: dict) -> None:
        await asyncio.sleep(0)
        await super().save(projection, key, data)


async def _drive_to_complete_phase(proj: ExecutionTodoProjection) -> None:
    """Advance exec-1/p-1 to COMPLETE_PHASE rank (just before finalization)."""
    await proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
    await proj.on_workspace_provisioned_for_phase(
        {"execution_id": "exec-1", "phase_id": "p-1", "workspace_id": "ws-1"}
    )
    await proj.on_agent_execution_completed(
        {"execution_id": "exec-1", "phase_id": "p-1", "session_id": "sess-1"}
    )
    await proj.on_artifacts_collected_for_phase(
        {"execution_id": "exec-1", "phase_id": "p-1", "artifact_ids": ["art-1"]}
    )


@pytest.mark.unit
class TestMonotonicRaceGuards:
    """Stale or concurrent writers cannot regress the per-phase highwater mark."""

    @pytest.mark.anyio
    async def test_stale_agent_completed_after_phase_done_is_noop(self) -> None:
        """A late AgentExecutionCompleted from a second writer (the
        coordinator subscription replaying history) must not regress a
        phase the processor already finalized (the D1 KeyError race)."""
        store = InMemoryProjectionStore()
        processor_proj = ExecutionTodoProjection(store=store)
        coordinator_proj = ExecutionTodoProjection(store=store)

        await _drive_to_complete_phase(processor_proj)
        await processor_proj.on_phase_completed({"execution_id": "exec-1", "phase_id": "p-1"})

        # Late duplicate from the persistent subscription
        await coordinator_proj.on_agent_execution_completed(
            {"execution_id": "exec-1", "phase_id": "p-1", "session_id": "sess-1"}
        )

        assert await processor_proj.get_pending("exec-1") == []
        record = await store.get("execution_todo", "exec-1")
        assert record is not None
        assert record["phase_progress"]["p-1"] == _RANK_PHASE_DONE

    @pytest.mark.anyio
    async def test_concurrent_stale_writer_cannot_regress_rank(self) -> None:
        """Two writers race on the same record with yielding store I/O.

        Precondition is RUN_AGENT rank so BOTH writers legitimately pass
        their rank pre-check; without the per-execution lock the lower-rank
        writer can read before, and save after, the finalizing writer,
        blindly overwriting _RANK_PHASE_DONE back to COLLECT_ARTIFACTS
        (the residual TOCTOU window behind the D1 KeyError). The lock
        makes the read-rank-check-save cycle atomic, so finalization wins
        regardless of interleaving.
        """
        for first_wins in (True, False):
            store = _YieldingStore()
            processor_proj = ExecutionTodoProjection(store=store)
            coordinator_proj = ExecutionTodoProjection(store=store)

            await processor_proj.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
            await processor_proj.on_workspace_provisioned_for_phase(
                {"execution_id": "exec-1", "phase_id": "p-1", "workspace_id": "ws-1"}
            )

            lower_rank_write = coordinator_proj.on_agent_execution_completed(
                {"execution_id": "exec-1", "phase_id": "p-1", "session_id": "sess-1"}
            )
            finalize = processor_proj.on_phase_completed(
                {"execution_id": "exec-1", "phase_id": "p-1"}
            )
            if first_wins:
                await asyncio.gather(lower_rank_write, finalize)
            else:
                await asyncio.gather(finalize, lower_rank_write)

            # The protected invariant is the monotonic highwater mark: once
            # PhaseCompleted is applied, no interleaving may leave the rank
            # below _RANK_PHASE_DONE (a regressed rank is what allowed the
            # processor to re-dispatch COLLECT_ARTIFACTS post-finalization).
            record = await store.get("execution_todo", "exec-1")
            assert record is not None
            assert record["phase_progress"]["p-1"] == _RANK_PHASE_DONE, (
                f"stale writer regressed the phase rank (first_wins={first_wins})"
            )

    @pytest.mark.anyio
    async def test_phase_progress_survives_next_phase_ready(self) -> None:
        """NextPhaseReady must preserve the highwater map and record the
        next phase at PROVISION_WORKSPACE rank, so a late event for the
        finalized phase cannot regress the todo list afterwards."""
        store = InMemoryProjectionStore()
        proj = ExecutionTodoProjection(store=store)

        await _drive_to_complete_phase(proj)
        await proj.on_phase_completed({"execution_id": "exec-1", "phase_id": "p-1"})
        await proj.on_next_phase_ready(
            {"execution_id": "exec-1", "next_phase_id": "p-2", "next_phase_order": 2}
        )

        record = await store.get("execution_todo", "exec-1")
        assert record is not None
        assert record["phase_progress"]["p-1"] == _RANK_PHASE_DONE
        assert record["phase_progress"]["p-2"] == _ACTION_RANK[TodoAction.PROVISION_WORKSPACE]

        # Late AgentExecutionCompleted for the finalized phase: no-op
        await proj.on_agent_execution_completed(
            {"execution_id": "exec-1", "phase_id": "p-1", "session_id": "sess-1"}
        )
        todos = await proj.get_pending("exec-1")
        assert [t.action for t in todos] == [TodoAction.PROVISION_WORKSPACE]
        assert todos[0].phase_id == "p-2"


# =========================================================================
# Restart resilience
# =========================================================================


@pytest.mark.unit
class TestRestartResilience:
    """State persists in the store across projection instance restarts."""

    @pytest.mark.anyio
    async def test_new_instance_same_store_sees_todos(self) -> None:
        """A fresh projection instance backed by the same store returns the same todos."""
        store = InMemoryProjectionStore()
        proj1 = ExecutionTodoProjection(store=store)
        await proj1.on_workflow_execution_started(TWO_PHASE_STARTED_EVENT)
        todos_before = await proj1.get_pending("exec-1")
        assert len(todos_before) == 1

        # Simulate restart: new projection instance, same store
        proj2 = ExecutionTodoProjection(store=store)
        todos_after = await proj2.get_pending("exec-1")
        assert len(todos_after) == 1
        assert todos_after[0].action == todos_before[0].action
        assert todos_after[0].phase_id == todos_before[0].phase_id
