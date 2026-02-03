"""Query for retrieving token usage metrics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GetTokenMetricsQuery:
    """Query to get token usage metrics for a session.

    Attributes:
        session_id: The session to get token metrics for.
        include_records: Whether to include individual token records.
    """

    session_id: str
    include_records: bool = True
