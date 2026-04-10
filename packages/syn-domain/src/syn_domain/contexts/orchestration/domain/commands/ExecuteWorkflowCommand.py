"""ExecuteWorkflow command - represents intent to execute a workflow."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("ExecuteWorkflow", "Starts execution of a workflow")
class ExecuteWorkflowCommand(BaseModel):
    """Command to start executing a workflow.

    The workflow must already exist. This command initiates
    the execution process with provided inputs.
    """

    model_config = ConfigDict(frozen=True)

    # Target aggregate - the workflow to execute
    aggregate_id: str = Field(..., min_length=1, description="Workflow ID to execute")

    # Input variables for the workflow
    inputs: dict[str, str] = Field(
        default_factory=dict,
        description="Input variables for the workflow phases",
    )

    # Optional execution context
    execution_id: str | None = Field(
        default=None,
        description="Custom execution ID (generated if not provided)",
    )

    # Primary task description — substituted for $ARGUMENTS in phase prompts
    task: str | None = Field(
        default=None,
        description="Primary task description, substituted for $ARGUMENTS in prompts",
    )

    # Dry run mode - validate without executing
    dry_run: bool = Field(
        default=False,
        description="If true, validate inputs but don't execute",
    )
