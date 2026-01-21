"""ExecuteCommandCommand - command to execute a command in workspace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from event_sourcing import Command

if TYPE_CHECKING:
    from aef_domain.contexts.workspaces._shared.value_objects import ExecutionResult


@dataclass
class ExecuteCommandCommand(Command):
    """Command to record execution of a command in workspace.

    Note: Actual execution is done by the application layer via IsolationBackendPort.
    This command records the result in the aggregate for event sourcing.

    Usage (application layer):
        # Execute via port
        result = await isolation_port.execute(handle, command)

        # Record in aggregate
        aggregate.execute_command(ExecuteCommandCommand(
            workspace_id=workspace_id,
            command=command,
            result=result,
        ))

    Attributes:
        workspace_id: Target workspace ID
        command: Command to execute (e.g., ["python", "script.py"])
        result: Execution result (provided by application layer)
        working_directory: Optional working directory override
        timeout_seconds: Optional timeout override
    """

    workspace_id: str
    command: list[str]
    result: ExecutionResult | None = None  # Provided by application layer

    # Optional overrides
    working_directory: str | None = None
    timeout_seconds: int | None = None
    environment: dict[str, str] = field(default_factory=dict)
