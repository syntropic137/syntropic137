"""Query DTO for listing workflow templates."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ListWorkflowsQuery:
    """Query to list workflow templates with optional filtering.

    Note: Templates don't have status. For execution status filtering,
    use ListWorkflowExecutionsQuery instead.
    """

    workflow_type_filter: str | None = None
    """Filter by workflow type (e.g., 'research', 'implementation')."""

    limit: int = 100
    """Maximum number of results to return."""

    offset: int = 0
    """Number of results to skip for pagination."""

    order_by: str = "-created_at"
    """Field to sort by. Prefix with '-' for descending order."""
