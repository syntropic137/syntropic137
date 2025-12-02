"""Workflow vertical slices.

Each slice is a self-contained unit handling a specific use case.
Slices can be commands (write operations) or queries (read operations).
"""

from .list_workflows import ListWorkflowsHandler, WorkflowListProjection

__all__ = [
    "ListWorkflowsHandler",
    "WorkflowListProjection",
]

