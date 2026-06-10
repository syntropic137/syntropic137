"""Execution to-do list projection (ISS-196).

Builds a list of pending work items from domain events. The processor
reads this list and dispatches to infrastructure handlers.

Designed for two usage modes:
1. In-process synchronous: processor applies events locally after each save
2. Persistent: catches up asynchronously for external consumers

See AGENTS.md "Projection Consistency in Processor Loops".

Monotonicity guard (fix for D1, stress 2026-06-10): the projection
record stores ``phase_progress: {phase_id -> max_action_rank_ever_seen}``.
Every advance-direction handler refuses to regress a phase below its
recorded rank. Without this, the in-process sync (processor) and the
persistent subscription (coordinator), both wired to the same
``projection_store``, race on the shared record, and an out-of-order
late event such as AgentExecutionCompleted overwrites a more recent
state, causing the processor to re-dispatch COLLECT_ARTIFACTS after the
workspace has already been finalized. The race manifested as
``KeyError: 'reply'`` in WorkflowExecutionProcessor at line 607
(``self._active_workspaces[todo.phase_id]``) on ~60% of stress runs.

Concurrency guard (hardening of D1): the rank check alone is a
read-then-write and the store has no conditional-write primitive
(InMemory dict set; Postgres blind upsert), so two writers in the same
process (processor sync + coordinator subscription run in the syn-api
process and share one store) could still interleave between the read
and the save. Every read-modify-write therefore runs under a
process-wide per-execution ``asyncio.Lock`` (class-level registry, so
all projection instances in the process serialize on the same lock),
and ``phase_progress`` is merged monotonically (max rank per phase)
against the freshly-read record at save time. The monotonic merge also
bounds the damage if a writer ever bypasses the lock (e.g. a future
out-of-process consumer): it can write stale ``items`` but can never
regress a phase's recorded rank. ``get_pending`` closes the remaining
gap by filtering out items whose rank sits below the phase's recorded
highwater mark, so a resurrected stale todo is never served.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

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
# Sentinel rank for phases that have already had PhaseCompleted applied;
# strictly greater than any TodoAction rank, so subsequent advance-
# direction handlers for the same phase become no-ops.
_RANK_PHASE_DONE = 99


def _merge_progress(existing: dict[str, int], updates: dict[str, int]) -> dict[str, int]:
    """Merge two phase-progress maps, keeping the max rank per phase.

    The monotonic merge guarantees a save can never regress a phase's
    recorded rank below what the freshly-read record already holds.
    """
    merged = dict(existing)
    for phase_id, rank in updates.items():
        merged[phase_id] = max(merged.get(phase_id, 0), rank)
    return merged


class ExecutionTodoProjection(AutoDispatchProjection):
    """To-do list read model for workflow execution processing.

    Maintains pending work items per execution. The processor reads
    get_pending() and dispatches each item to its handler.

    Concurrency: multiple projection instances in one process (the
    processor's in-process sync and the coordinator subscription) share
    the same store, so every read-modify-write runs under a class-level
    per-execution asyncio.Lock. See the module docstring.
    """

    PROJECTION_NAME = "execution_todo"
    VERSION = 1

    # Class-level so all instances in the process serialize per execution.
    _execution_locks: ClassVar[dict[str, asyncio.Lock]] = {}

    def __init__(self, store: ProjectionStore) -> None:
        """Initialize with a projection store."""
        self._store = store

    @classmethod
    def _lock_for(cls, execution_id: str) -> asyncio.Lock:
        """Get (or lazily create) the per-execution write lock."""
        lock = cls._execution_locks.get(execution_id)
        if lock is None:
            lock = asyncio.Lock()
            cls._execution_locks[execution_id] = lock
        return lock

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

        Defense in depth: items whose action rank is strictly below the
        phase's recorded highwater mark are filtered out. Every save site
        writes an item together with its rank, so fresh items always have
        rank == progress; only resurrected/stale items rank below. A
        writer that bypasses the per-execution lock (e.g. a future
        out-of-process consumer on a shared Postgres store, where the
        asyncio lock is useless) can persist stale ``items`` but can never
        regress ``phase_progress`` (monotonic merge), so this read-time
        filter guarantees a stale todo is never served to the processor.
        Phase-done (_RANK_PHASE_DONE) suppresses every action for that
        phase; items rank-equal to progress are still served.
        """
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        if data is None:
            return []
        items = [_item_from_dict(d) for d in data.get("items", [])]
        raw_progress = data.get("phase_progress")
        progress: dict[str, int] = raw_progress if isinstance(raw_progress, dict) else {}
        return [
            item
            for item in items
            if item.phase_id is None
            or item.action not in _ACTION_RANK
            or progress.get(item.phase_id, 0) <= _ACTION_RANK[item.action]
        ]

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
        # leave it alone; the executor has moved on.
        await self._advance_phase_todo(
            execution_id,
            phase_id,
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.PROVISION_WORKSPACE,
                phase_id=phase_id,
            ),
        )

    async def on_workspace_provisioned_for_phase(self, event_data: dict) -> None:
        """Workspace ready → run agent."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return
        phase_id = event_data.get("phase_id")
        if not isinstance(phase_id, str):
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
        async with self._lock_for(execution_id):
            current, progress = await self._read_state(execution_id)
            remaining = [
                t
                for t in current
                if not (t.action == TodoAction.COMPLETE_PHASE and t.phase_id == phase_id)
            ]
            await self._save_state(
                execution_id,
                remaining,
                _merge_progress(progress, {phase_id: _RANK_PHASE_DONE}),
            )

    async def on_next_phase_ready(self, event_data: dict) -> None:
        """Aggregate decided next phase → append PROVISION_WORKSPACE to-do.

        Uses append (not replace) because ArtifactsCollectedForPhase and
        NextPhaseReady are emitted in the same save. The projection sees
        them sequentially: on_artifacts_collected sets COMPLETE_PHASE, then
        on_next_phase_ready must ADD (not overwrite) PROVISION_WORKSPACE.

        Preserves ``phase_progress`` (the per-phase highwater map) and
        records the next phase at PROVISION_WORKSPACE rank, so a late
        AgentExecutionCompleted for an already-finalized phase cannot
        regress the todo list after this save.
        """
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        next_phase_id = event_data.get("next_phase_id")
        async with self._lock_for(execution_id):
            current, progress = await self._read_state(execution_id)
            current.append(
                TodoItem(
                    execution_id=execution_id,
                    action=TodoAction.PROVISION_WORKSPACE,
                    phase_id=next_phase_id,
                )
            )
            if isinstance(next_phase_id, str):
                progress = _merge_progress(
                    progress,
                    {next_phase_id: _ACTION_RANK[TodoAction.PROVISION_WORKSPACE]},
                )
            await self._save_state(execution_id, current, progress)

    async def on_workflow_completed(self, event_data: dict) -> None:
        """Workflow completed → clear all todos."""
        await self._clear_execution(event_data.get("execution_id", ""))

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Workflow failed → clear all todos."""
        await self._clear_execution(event_data.get("execution_id", ""))

    async def on_execution_cancelled(self, event_data: dict) -> None:
        """Execution cancelled → clear all todos."""
        await self._clear_execution(event_data.get("execution_id", ""))

    async def on_workflow_interrupted(self, event_data: dict) -> None:
        """Workflow interrupted → clear all todos."""
        await self._clear_execution(event_data.get("execution_id", ""))

    # =========================================================================
    # Internal
    # =========================================================================

    async def _read_state(self, execution_id: str) -> tuple[list[TodoItem], dict[str, int]]:
        """Read (items, phase_progress) from the record. Empty when absent."""
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not data:
            return [], {}
        items = [_item_from_dict(d) for d in data.get("items", [])]
        progress = data.get("phase_progress")
        return items, dict(progress) if isinstance(progress, dict) else {}

    async def _save_state(
        self, execution_id: str, items: list[TodoItem], progress: dict[str, int]
    ) -> None:
        """Persist (items, phase_progress) for an execution."""
        await self._store.save(
            self.PROJECTION_NAME,
            execution_id,
            {
                "execution_id": execution_id,
                "items": [_item_to_dict(t) for t in items],
                "phase_progress": progress,
            },
        )

    async def _advance_phase_todo(
        self, execution_id: str, phase_id: str, new_todo: TodoItem
    ) -> None:
        """Replace todos AND bump the phase's monotonic rank.

        Runs under the per-execution lock so the read-rank-check-save
        cycle is atomic against every other in-process writer: a stale
        writer cannot regress a phase that a concurrent writer already
        advanced. The save merges ``phase_progress`` monotonically as a
        second line of defense (see module docstring).
        """
        async with self._lock_for(execution_id):
            _items, progress = await self._read_state(execution_id)
            new_rank = _ACTION_RANK[new_todo.action]
            if progress.get(phase_id, 0) >= new_rank:
                return  # A more recent writer is ahead; no-op.
            await self._save_state(
                execution_id,
                [new_todo],
                _merge_progress(progress, {phase_id: new_rank}),
            )

    async def _clear_execution(self, execution_id: str) -> None:
        """Delete the record (terminal event) and release its lock entry."""
        if not execution_id:
            return
        async with self._lock_for(execution_id):
            await self._store.delete(self.PROJECTION_NAME, execution_id)
        # Drop the lock entry so the registry does not grow unboundedly
        # in long-running processes. A writer arriving after this point
        # gets a fresh lock, which is fine: the record is gone and any
        # late advance event simply re-creates then re-deletes on the
        # next terminal event (pre-existing behaviour).
        self._execution_locks.pop(execution_id, None)
