"""Record Trigger Dispatch Completed command.

Command to record that a trigger's workflow dispatch completed successfully.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class RecordTriggerDispatchCompletedCommand:
    """Command to record a successful trigger dispatch.

    Attributes:
        trigger_id: ID of the trigger rule.
        execution_id: ID of the dispatched workflow execution.
        workflow_id: Workflow that was dispatched.
        command_id: Unique identifier for this command.
    """

    trigger_id: str
    execution_id: str
    workflow_id: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.trigger_id
