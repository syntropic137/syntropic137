"""Get Installation query.

Query to retrieve the current state of a GitHub App installation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetInstallationQuery:
    """Query to get a GitHub App installation by ID.

    Attributes:
        query_id: Unique identifier for this query.
        installation_id: GitHub installation ID to retrieve.
    """

    installation_id: str
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.installation_id:
            raise ValueError("installation_id is required")
