"""Get Organization query.

Query to retrieve the current state of an organization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetOrganizationQuery:
    """Query to get an organization by ID.

    Attributes:
        organization_id: Organization ID to retrieve.
        query_id: Unique identifier for this query.
    """

    organization_id: str
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.organization_id:
            raise ValueError("organization_id is required")
