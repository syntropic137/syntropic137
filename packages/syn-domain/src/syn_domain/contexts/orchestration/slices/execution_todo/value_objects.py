"""Value objects for the execution to-do list projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TodoAction(str, Enum):
    """Action the processor should dispatch for a to-do item.

    Lifecycle per phase:
        PROVISION_WORKSPACE → RUN_AGENT → COLLECT_ARTIFACTS → COMPLETE_PHASE
            ↓ (NextPhaseReady? → back to PROVISION_WORKSPACE)
            ↓ (No more phases? → COMPLETE_EXECUTION)
    """

    PROVISION_WORKSPACE = "provision_workspace"
    RUN_AGENT = "run_agent"
    COLLECT_ARTIFACTS = "collect_artifacts"
    COMPLETE_PHASE = "complete_phase"
    COMPLETE_EXECUTION = "complete_execution"


@dataclass(frozen=True)
class TodoItem:
    """A single pending work item for the processor.

    The processor reads these and dispatches to the appropriate handler.
    Zero business logic in the processor — all decisions made by the aggregate.
    """

    execution_id: str
    action: TodoAction
    phase_id: str | None = None
    workspace_id: str | None = None
    session_id: str | None = None
