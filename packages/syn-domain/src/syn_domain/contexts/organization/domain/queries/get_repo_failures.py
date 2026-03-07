"""Get Repo Failures query.

Query to retrieve recent failures for a repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetRepoFailuresQuery:
    """Query to get a repository's recent failures.

    Attributes:
        repo_id: Repository ID to retrieve failures for.
        limit: Maximum number of failures to return.
        offset: Number of entries to skip (for pagination).
        query_id: Unique identifier for this query.
    """

    repo_id: str
    limit: int = 20
    offset: int = 0
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.repo_id:
            raise ValueError("repo_id is required")
