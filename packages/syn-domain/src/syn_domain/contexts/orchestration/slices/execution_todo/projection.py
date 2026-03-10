"""Execution to-do list projection (ISS-196).

Builds a list of pending work items from domain events. The processor
reads this list and dispatches to infrastructure handlers.

Designed for two usage modes:
1. In-process synchronous: processor applies events locally after each save
2. Persistent: catches up asynchronously for external consumers

See AGENTS.md "Projection Consistency in Processor Loops".
"""

from __future__ import annotations

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.slices.execution_todo.value_objects import (
    TodoAction,
    TodoItem,
)


class ExecutionTodoProjection(AutoDispatchProjection):
    """To-do list read model for workflow execution processing.

    Maintains pending work items per execution. The processor reads
    get_pending() and dispatches each item to its handler.

    Thread-safety: designed for single-processor use. Each processor
    instance owns its own projection instance.
    """

    PROJECTION_NAME = "execution_todo"
    VERSION = 1

    def __init__(self) -> None:
        """Initialize with empty to-do state."""
        # execution_id → list of pending TodoItems
        self._todos: dict[str, list[TodoItem]] = {}

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version."""
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear all to-do data (for rebuild)."""
        self._todos.clear()

    # =========================================================================
    # Query interface
    # =========================================================================

    def get_pending(self, execution_id: str) -> list[TodoItem]:
        """Get all pending to-do items for an execution.

        Returns items in insertion order (FIFO).
        """
        return list(self._todos.get(execution_id, []))

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

        self._todos[execution_id] = [
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.PROVISION_WORKSPACE,
                phase_id=first_phase["phase_id"],
            ),
        ]

    async def on_workspace_provisioned_for_phase(self, event_data: dict) -> None:
        """Workspace ready → run agent."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        self._replace_todo(
            execution_id,
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.RUN_AGENT,
                phase_id=event_data.get("phase_id"),
                workspace_id=event_data.get("workspace_id"),
            ),
        )

    async def on_agent_execution_completed(self, event_data: dict) -> None:
        """Agent finished → collect artifacts."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        self._replace_todo(
            execution_id,
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.COLLECT_ARTIFACTS,
                phase_id=event_data.get("phase_id"),
                session_id=event_data.get("session_id"),
            ),
        )

    async def on_artifacts_collected_for_phase(self, event_data: dict) -> None:
        """Artifacts collected → complete phase."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        self._replace_todo(
            execution_id,
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.COMPLETE_PHASE,
                phase_id=event_data.get("phase_id"),
            ),
        )

    async def on_phase_completed(self, event_data: dict) -> None:
        """Phase completed → remove to-do (next phase decided by aggregate)."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        # Clear current to-do — NextPhaseReady or COMPLETE_EXECUTION comes next
        self._todos.pop(execution_id, None)

    async def on_next_phase_ready(self, event_data: dict) -> None:
        """Aggregate decided next phase → provision workspace for it."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        self._todos[execution_id] = [
            TodoItem(
                execution_id=execution_id,
                action=TodoAction.PROVISION_WORKSPACE,
                phase_id=event_data.get("next_phase_id"),
            ),
        ]

    async def on_workflow_completed(self, event_data: dict) -> None:
        """Workflow completed → clear all todos."""
        execution_id = event_data.get("execution_id", "")
        self._todos.pop(execution_id, None)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Workflow failed → clear all todos."""
        execution_id = event_data.get("execution_id", "")
        self._todos.pop(execution_id, None)

    async def on_execution_cancelled(self, event_data: dict) -> None:
        """Execution cancelled → clear all todos."""
        execution_id = event_data.get("execution_id", "")
        self._todos.pop(execution_id, None)

    async def on_workflow_interrupted(self, event_data: dict) -> None:
        """Workflow interrupted → clear all todos."""
        execution_id = event_data.get("execution_id", "")
        self._todos.pop(execution_id, None)

    # =========================================================================
    # Internal
    # =========================================================================

    def _replace_todo(self, execution_id: str, new_todo: TodoItem) -> None:
        """Replace all pending todos for an execution with a single new one."""
        self._todos[execution_id] = [new_todo]
