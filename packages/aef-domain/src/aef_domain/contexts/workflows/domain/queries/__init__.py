"""Workflow query DTOs.

These data transfer objects define the parameters for read operations
in the workflow context.
"""

from .get_workflow_detail import GetWorkflowDetailQuery
from .list_workflows import ListWorkflowsQuery

__all__ = [
    "GetWorkflowDetailQuery",
    "ListWorkflowsQuery",
]
