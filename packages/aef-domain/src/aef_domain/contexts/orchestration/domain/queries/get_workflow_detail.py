"""Query DTO for getting workflow detail."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GetWorkflowDetailQuery:
    """Query to get detailed information about a specific workflow.

    This is a pure data transfer object that contains no business logic.
    """

    workflow_id: str
    """The unique identifier of the workflow to retrieve."""

    include_phases: bool = True
    """Whether to include phase information in the response."""

    include_sessions: bool = False
    """Whether to include session information in the response."""

    include_artifacts: bool = False
    """Whether to include artifact information in the response."""
