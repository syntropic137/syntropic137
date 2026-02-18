"""Workspace aggregate - isolated execution environments.

Aggregate Root: WorkspaceAggregate
Entities: IsolationHandle (has identity: isolation_id)
Value Objects: SecurityPolicy, ExecutionResult, WorkspaceStatus, etc.

This aggregate manages the lifecycle of isolated workspaces:
1. Creation: Provision isolation environment
2. Token Injection: Inject API tokens
3. Command Execution: Execute commands and stream events
4. Termination: Clean up resources

All entities and value objects are accessed through the aggregate root.
"""

from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
    WorkspaceAggregate,
)

__all__ = ["WorkspaceAggregate"]
