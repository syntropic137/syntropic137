"""ExecuteWorkflow command handler - VSA compliance wrapper.

This handler satisfies VSA architectural requirements by providing a
standalone handler class. The actual business logic lives in the
WorkflowExecutionEngine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ExecuteWorkflowCommand import ExecuteWorkflowCommand
    from .WorkflowExecutionEngine import WorkflowExecutionEngine, WorkflowExecutionResult


class ExecuteWorkflowHandler:
    """Handler for ExecuteWorkflow command (VSA compliance).

    This is a thin wrapper that delegates to the WorkflowExecutionEngine.
    VSA requires this standalone handler class for architectural consistency.

    The engine handles the actual orchestration:
    - Workflow validation and loading
    - Phase execution sequencing
    - Agent coordination
    - Artifact creation
    - Metrics aggregation
    - Event persistence
    """

    def __init__(self, execution_engine: WorkflowExecutionEngine) -> None:
        """Initialize handler with execution engine.

        Args:
            execution_engine: WorkflowExecutionEngine for orchestrating execution
        """
        self.execution_engine = execution_engine

    async def handle(self, command: ExecuteWorkflowCommand) -> WorkflowExecutionResult:
        """Handle ExecuteWorkflow command.

        Args:
            command: ExecuteWorkflowCommand with workflow ID and inputs

        Returns:
            WorkflowExecutionResult with execution details and metrics

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
            ValidationError: If inputs are invalid
        """
        # Delegate to execution engine
        result = await self.execution_engine.execute(
            workflow_id=command.aggregate_id,
            inputs=command.inputs,
            execution_id=command.execution_id,
        )

        return result
