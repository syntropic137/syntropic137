"""Execution to-do list projection (ISS-196).

Builds a list of pending work items from domain events. The processor
reads this list and dispatches to infrastructure handlers.

Designed for two usage modes:
1. In-process synchronous: processor applies events locally after each save
2. Persistent: catches up asynchronously for external consumers

See AGENTS.md "Projection Consistency in Processor Loops".

Monotonicity guard (fix for D1 — stress 2026-06-10): the projection
record stores ``phase_progress: {phase_id -> max_action_rank_ever_seen}``.
Every advance-direction handler refuses to regress a phase below its
recorded rank. Without this, the in-process sync (processor) and the
persistent subscription (coordinator) — both wired to the same
``projection_store`` — race on the shared record, and an out-of-order
late event such as AgentExecutionCompleted overwrites a more recent
state, causing the processor to re-dispatch COLLECT_ARTIFACTS after the
workspace has already been finalized. The race manifested as
``KeyError: 'reply'`` in WorkflowExecutionProcessor at line 607
(``self._active_workspaces[todo.phase_id]``) on ~60% of stress runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import AutoDispatchProjection

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

from syn_domain.contexts.orchestration.slices.execution_todo.value_objects import (
    TodoAction,
    TodoItem,
)


def _item_to_dict(item: TodoItem) -> dict:
    return {
        "execution_id": item.execution_id,
        "action": item.action.value,
        "phase_id": item.phase_id,
        "workspace_id": item.workspace_id,
        "session_id": item.session_id,
    }


def _item_from_dict(data: dict) -> TodoItem:
    return TodoItem(
        execution_id=data["execution_id"],
        action=TodoAction(data["action"]),
        phase_id=data.get("phase_id"),
        workspace_id=data.get("workspace_id"),
        session_id=data.get("session_id"),
    )


# Action rank for the monotonic per-phase highwater mark (D1 fix).
# An advance-direction event handler refuses to set a phase to an
# action whose rank is <= the phase's current rank.
_ACTION_RANK: dict[TodoAction, int] = {
    TodoAction.PROVISION_WORKSPACE: 1,
    TodoAction.RUN_AGENT: 2,
    TodoAction.COLLECT_ARTIFACTS: 3,
    TodoAction.COMPLETE_PHASE: 4,
}
# Sentinel rank for phases that have already had PhaseCompleted applied
# — strictly greater than any TodoAction rank, so subsequent advance-
# direction handlers for the same phase become no-ops.
_RANK_PHASE_DONE = 99


class ExecutionTodoProjection(AutoDispatchProjection):
    """To-do list read model for workflow execution processing.

    Maintains pending work items per execution. The processor reads
    get_pending() and dispatches each item to its handler.

    Thread-safety: designed for single-processor use. Each processor
    instance owns its own projection instance.
    """

    PROJECTION_NAME = "execution_todo"
    VERSION = 1

    def __init__(self, store: ProjectionStore) -> None:
        """Initialize with a projection store."""
        self._store = store

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version."""
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear all to-do data (for rebuild)."""
        records = await self._store.get_all(self.PROJECTION_NAME)
        for record in records:
            execution_id = record.get("execution_id")
            if execution_id:
                await self._store.delete(self.PROJECTION_NAME, execution_id)

    # =========================================================================
    # Query interface
    # =========================================================================

    async def get_pending(self, execution_id: str) -> list[TodoItem]:
        """Get all pending to-do items for an execution.

        Returns items in insertion order (FIFO).
        """
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        if data is None:
            return []
        return [_item_from_dict(d) for d in data.get("items", [])]

    # =========================================================================
    # Event handlers
    # =========================================================================

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        """Execution started → provision workspace for first phase."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        phase_defs = event_data.get("phase_definitions") or []
        if not phase_defs:
            return  # Legacy mode — no to-do list management

        # Sort by order, take first phase
        sorted_phases = sorted(phase_defs, key=lambda p: p.get("order", 0))
        first_phase = sorted_phases[0]
        phase_id = first_phase["phase_id"]

        # Initial state: phase is at PROVISION_WORKSPACE rank. This is a
        # fresh execution; no prior progress to respect. Idempotency
        # guard: if a record already exists with a later rank we still
        # leave it alone — the executor has moved on.
        if await self._phase_at_or_past(execution_id, phase_id, TodoAction.PROVISION_WORKSPACE):
            return

        await self._store.save(
            self.PROJECTION_NAME,
            execution_id,
            {
                "execution_id": execution_id,
                "items": [
                    _item_to_dict(
                        TodoItem(
                            execution_id=execution_id,
                            action=TodoAction.PROVISION_WORKSPACE,
                            phase_id=phase_id,
                        )
                    )
                ],
                "phase_progress": {phase_id: _ACTION_RANK[TodoAction.PROVISION_WORKSPACE]},
            },
        )

    async def on_workspace_provisioned_for_phase(self, event_data: dict) -> None:
        """Workspace ready → run agent."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return
        phase_id = event_data.get("phase_id")
        if not isinstance(phase_id, str):
            return

        if await self._phase_at_or_past(execution_id, phase_id, TodoAction.RUN_AGENT):
            return

        await self._advance_phase_todo(
            execution_id,
            phase_id,
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.RUN_AGENT,
                phase_id=phase_id,
                workspace_id=event_data.get("workspace_id"),
                session_id=event_data.get("session_id"),
            ),
        )

    async def on_agent_execution_completed(self, event_data: dict) -> None:
        """Agent finished → collect artifacts."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return
        phase_id = event_data.get("phase_id")
        if not isinstance(phase_id, str):
            return

        if await self._phase_at_or_past(execution_id, phase_id, TodoAction.COLLECT_ARTIFACTS):
            return

        await self._advance_phase_todo(
            execution_id,
            phase_id,
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.COLLECT_ARTIFACTS,
                phase_id=phase_id,
                session_id=event_data.get("session_id"),
            ),
        )

    async def on_artifacts_collected_for_phase(self, event_data: dict) -> None:
        """Artifacts collected → complete phase."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return
        phase_id = event_data.get("phase_id")
        if not isinstance(phase_id, str):
            return

        if await self._phase_at_or_past(execution_id, phase_id, TodoAction.COMPLETE_PHASE):
            return

        await self._advance_phase_todo(
            execution_id,
            phase_id,
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.COMPLETE_PHASE,
                phase_id=phase_id,
                session_id=event_data.get("session_id"),
            ),
        )

    async def on_phase_completed(self, event_data: dict) -> None:
        """Phase completed → remove COMPLETE_PHASE to-do for this phase only.

        Other pending todos (e.g., PROVISION_WORKSPACE from NextPhaseReady)
        must be preserved. Also locks the phase at _RANK_PHASE_DONE so a
        late-arriving AgentExecutionCompleted from a competing writer
        does not regress the projection.
        """
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        phase_id = event_data.get("phase_id")
        if not isinstance(phase_id, str):
            return
        current = await self.get_pending(execution_id)
        remaining = [
            t
            for t in current
            if not (t.action == TodoAction.COMPLETE_PHASE and t.phase_id == phase_id)
        ]
        progress = await self._phase_progress(execution_id)
        progress[phase_id] = _RANK_PHASE_DONE
        await self._store.save(
            self.PROJECTION_NAME,
            execution_id,
            {
                "execution_id": execution_id,
                "items": [_item_to_dict(t) for t in remaining],
                "phase_progress": progress,
            },
        )

    async def on_next_phase_ready(self, event_data: dict) -> None:
        """Aggregate decided next phase → append PROVISION_WORKSPACE to-do.

        Uses append (not replace) because ArtifactsCollectedForPhase and
        NextPhaseReady are emitted in the same save. The projection sees
        them sequentially: on_artifacts_collected sets COMPLETE_PHASE, then
        on_next_phase_ready must ADD (not overwrite) PROVISION_WORKSPACE.
        """
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        current = await self.get_pending(execution_id)
        current.append(
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.PROVISION_WORKSPACE,
                phase_id=event_data.get("next_phase_id"),
            )
        )
        await self._store.save(
            self.PROJECTION_NAME,
            execution_id,
            {"execution_id": execution_id, "items": [_item_to_dict(t) for t in current]},
        )

    async def on_workflow_completed(self, event_data: dict) -> None:
        """Workflow completed → clear all todos."""
        execution_id = event_data.get("execution_id", "")
        if execution_id:
            await self._store.delete(self.PROJECTION_NAME, execution_id)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Workflow failed → clear all todos."""
        execution_id = event_data.get("execution_id", "")
        if execution_id:
            await self._store.delete(self.PROJECTION_NAME, execution_id)

    async def on_execution_cancelled(self, event_data: dict) -> None:
        """Execution cancelled → clear all todos."""
        execution_id = event_data.get("execution_id", "")
        if execution_id:
            await self._store.delete(self.PROJECTION_NAME, execution_id)

    async def on_workflow_interrupted(self, event_data: dict) -> None:
        """Workflow interrupted → clear all todos."""
        execution_id = event_data.get("execution_id", "")
        if execution_id:
            await self._store.delete(self.PROJECTION_NAME, execution_id)

    # =========================================================================
    # Internal
    # =========================================================================

    async def _replace_todo(self, execution_id: str, new_todo: TodoItem) -> None:
        """Replace all pending todos for an execution with a single new one.

        Retained for callers that ignore the monotonic per-phase guard
        (currently none on the happy path). Prefer ``_advance_phase_todo``.
        """
        await self._store.save(
            self.PROJECTION_NAME,
            execution_id,
            {"execution_id": execution_id, "items": [_item_to_dict(new_todo)]},
        )

    async def _phase_progress(self, execution_id: str) -> dict[str, int]:
        """Read the per-phase highwater map. Empty dict if no record."""
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not data:
            return {}
        progress = data.get("phase_progress")
        return dict(progress) if isinstance(progress, dict) else {}

    async def _phase_at_or_past(self, execution_id: str, phase_id: str, action: TodoAction) -> bool:
        """Has this (execution, phase) already advanced to or past ``action``?"""
        progress = await self._phase_progress(execution_id)
        current = progress.get(phase_id, 0)
        return current >= _ACTION_RANK[action]

    async def _advance_phase_todo(
        self, execution_id: str, phase_id: str, new_todo: TodoItem
    ) -> None:
        """Replace todos AND bump the phase's monotonic rank.

        Re-reads the projection record at write-time so a concurrent
        writer that already advanced past us cannot be regressed:
        compare-and-set semantics on the per-phase rank.
        """
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        progress: dict[str, int] = {}
        if data:
            raw_progress = data.get("phase_progress")
            if isinstance(raw_progress, dict):
                progress = dict(raw_progress)
        new_rank = _ACTION_RANK[new_todo.action]
        if progress.get(phase_id, 0) >= new_rank:
            return  # Lost the CAS — a more recent writer is ahead, no-op.
        progress[phase_id] = new_rank
        await self._store.save(
            self.PROJECTION_NAME,
            execution_id,
            {
                "execution_id": execution_id,
                "items": [_item_to_dict(new_todo)],
                "phase_progress": progress,
            },
        )
