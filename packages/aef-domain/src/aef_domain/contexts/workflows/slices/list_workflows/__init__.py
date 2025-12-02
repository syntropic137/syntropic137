"""List Workflows Query Slice.

This vertical slice handles the query operation for listing workflows.
It includes:
- WorkflowListProjection: Builds the read model from events
- ListWorkflowsHandler: Handles the query and returns data

This slice is self-contained and can be developed/tested independently.
"""

from .handler import ListWorkflowsHandler
from .projection import WorkflowListProjection

__all__ = [
    "ListWorkflowsHandler",
    "WorkflowListProjection",
]

