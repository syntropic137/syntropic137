"""Query DTO for listing workflows."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ListWorkflowsQuery:
    """Query to list all workflows with optional filtering.

    This is a pure data transfer object that contains no business logic.
    It simply defines the parameters for the query operation.
    """

    status_filter: str | None = None
    """Filter by workflow status (e.g., 'pending', 'in_progress', 'completed')."""

    workflow_type_filter: str | None = None
    """Filter by workflow type."""

    limit: int = 100
    """Maximum number of results to return."""

    offset: int = 0
    """Number of results to skip for pagination."""

    order_by: str = "-created_at"
    """Field to sort by. Prefix with '-' for descending order."""
