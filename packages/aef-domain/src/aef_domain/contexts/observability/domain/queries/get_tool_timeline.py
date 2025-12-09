"""Query for retrieving tool execution timeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GetToolTimelineQuery:
    """Query to get tool execution timeline for a session.

    Attributes:
        session_id: The session to get tool timeline for.
        limit: Maximum number of executions to return.
        include_blocked: Whether to include blocked tool executions.
    """

    session_id: str
    limit: int = 100
    include_blocked: bool = True
