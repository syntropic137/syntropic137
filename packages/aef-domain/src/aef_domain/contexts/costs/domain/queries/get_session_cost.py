"""Query for retrieving session cost."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GetSessionCostQuery:
    """Query to get cost for a session.

    Attributes:
        session_id: The session to get cost for.
        include_breakdown: Whether to include model/tool breakdowns.
    """

    session_id: str
    include_breakdown: bool = True
