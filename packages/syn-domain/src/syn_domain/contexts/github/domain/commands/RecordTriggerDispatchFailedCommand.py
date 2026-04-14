"""Record Trigger Dispatch Failed command.

Command to record that a trigger's workflow dispatch failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class RecordTriggerDispatchFailedCommand:
    """Command to record a failed trigger dispatch.

    Attributes:
        trigger_id: ID of the trigger rule.
        execution_id: ID of the attempted workflow execution.
        workflow_id: Workflow that failed to dispatch.
        failure_reason: Reason the dispatch failed.
        command_id: Unique identifier for this command.
    """

    trigger_id: str
    execution_id: str
    workflow_id: str = ""
    failure_reason: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.trigger_id
