"""Get Repo query.

Query to retrieve the current state of a repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetRepoQuery:
    """Query to get a repository by ID.

    Attributes:
        repo_id: Repository ID to retrieve.
        query_id: Unique identifier for this query.
    """

    repo_id: str
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.repo_id:
            raise ValueError("repo_id is required")
