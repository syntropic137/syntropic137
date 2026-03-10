"""Get Repo Health query.

Query to retrieve the health snapshot for a repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetRepoHealthQuery:
    """Query to get a repository's health snapshot.

    Attributes:
        repo_id: Repository ID to retrieve health for.
        window_hours: Time window for trend calculation (default 168 = 7 days).
        query_id: Unique identifier for this query.
    """

    repo_id: str
    repo_full_name: str = ""
    window_hours: int = 168
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.repo_id:
            raise ValueError("repo_id is required")
