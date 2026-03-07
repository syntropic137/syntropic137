"""Get Repo Cost query.

Query to retrieve the cost breakdown for a repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetRepoCostQuery:
    """Query to get a repository's cost breakdown.

    Attributes:
        repo_id: Repository ID to retrieve costs for.
        window_hours: Time window for cost aggregation (default 720 = 30 days).
        query_id: Unique identifier for this query.
    """

    repo_id: str
    window_hours: int = 720
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.repo_id:
            raise ValueError("repo_id is required")
