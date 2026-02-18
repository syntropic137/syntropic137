"""Query DTO for listing artifacts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ListArtifactsQuery:
    """Query to list artifacts with optional filtering.

    This is a pure data transfer object that contains no business logic.
    """

    workflow_id: str | None = None
    """Filter by workflow ID."""

    session_id: str | None = None
    """Filter by session ID."""

    phase_id: str | None = None
    """Filter by phase ID."""

    artifact_type_filter: str | None = None
    """Filter by artifact type."""

    limit: int = 100
    """Maximum number of results to return."""

    offset: int = 0
    """Number of results to skip for pagination."""

    order_by: str = "-created_at"
    """Field to sort by. Prefix with '-' for descending order."""
