"""Orchestration bounded context.

This context manages:
- Workflow execution lifecycle
- Workspace isolation and management
- Multi-phase execution coordination

Aggregates:
- WorkspaceAggregate: Isolated execution environments
- WorkflowAggregate: Workflow definitions
- WorkflowExecutionAggregate: Execution lifecycle

Refactored from: workflows/ + workspaces/ bounded contexts (2026-02-02)
See: ADR-020-bounded-context-aggregate-relationship.md
"""
