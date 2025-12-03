"""Workflow read models (DTOs for query responses).

These are lightweight, read-optimized data transfer objects
returned by query handlers. They are independent of the domain
aggregate structure.
"""

from .workflow_detail import WorkflowDetail
from .workflow_summary import WorkflowSummary

__all__ = [
    "WorkflowDetail",
    "WorkflowSummary",
]
