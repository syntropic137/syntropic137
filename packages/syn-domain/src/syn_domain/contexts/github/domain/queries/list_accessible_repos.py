"""List Accessible Repos query.

Query to list repositories accessible to a GitHub App installation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ListAccessibleReposQuery:
    """Query to list repositories accessible to an installation.

    Attributes:
        query_id: Unique identifier for this query.
        installation_id: GitHub installation ID.
        include_private: Whether to include private repositories.
    """

    installation_id: str
    include_private: bool = True
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.installation_id:
            raise ValueError("installation_id is required")
