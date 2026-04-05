"""Get Repo Sessions query.

Query to retrieve agent sessions for a repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetRepoSessionsQuery:
    """Query to get a repository's agent sessions.

    Attributes:
        repo_id: Repository ID to retrieve sessions for.
        limit: Maximum number of sessions to return.
        offset: Number of entries to skip (for pagination).
        query_id: Unique identifier for this query.
    """

    repo_id: str
    repo_full_name: str = ""
    limit: int = 50
    offset: int = 0
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.repo_id:
            raise ValueError("repo_id is required")
