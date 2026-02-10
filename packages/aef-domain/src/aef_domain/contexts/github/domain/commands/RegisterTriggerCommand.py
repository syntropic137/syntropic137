"""Register Trigger command.

Command to register a new trigger rule for a GitHub repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class RegisterTriggerCommand:
    """Command to register a new trigger rule.

    Attributes:
        name: Human-readable name for the trigger.
        event: GitHub event type (e.g. "check_run.completed").
        conditions: List of condition dicts with field, operator, value.
        repository: Target repository (owner/repo).
        installation_id: GitHub App installation ID.
        workflow_id: Workflow to dispatch when trigger fires.
        input_mapping: Map of workflow input names to payload paths.
        config: Safety configuration dict.
        created_by: User or agent registering the trigger.
        command_id: Unique identifier for this command.
    """

    name: str
    event: str
    conditions: tuple[dict, ...] = ()
    repository: str = ""
    installation_id: str = ""
    workflow_id: str = ""
    input_mapping: tuple[tuple[str, str], ...] = ()
    config: tuple[tuple[str, object], ...] = ()
    created_by: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.name:
            raise ValueError("name is required")
        if not self.event:
            raise ValueError("event is required")
        if not self.repository:
            raise ValueError("repository is required")
        if not self.workflow_id:
            raise ValueError("workflow_id is required")
