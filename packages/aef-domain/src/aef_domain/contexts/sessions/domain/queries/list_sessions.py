"""Query DTO for listing sessions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ListSessionsQuery:
    """Query to list agent sessions with optional filtering.

    This is a pure data transfer object that contains no business logic.
    """

    workflow_id: str | None = None
    """Filter by workflow ID."""

    agent_type_filter: str | None = None
    """Filter by agent type."""

    status_filter: str | None = None
    """Filter by session status."""

    limit: int = 100
    """Maximum number of results to return."""

    offset: int = 0
    """Number of results to skip for pagination."""

    order_by: str = "-started_at"
    """Field to sort by. Prefix with '-' for descending order."""
