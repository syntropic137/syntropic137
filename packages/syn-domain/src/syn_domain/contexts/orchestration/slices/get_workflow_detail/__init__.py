"""Get workflow detail query slice."""

from .GetWorkflowDetailHandler import GetWorkflowDetailHandler
from .projection import WorkflowDetailProjection

__all__ = [
    "GetWorkflowDetailHandler",
    "WorkflowDetailProjection",
]
