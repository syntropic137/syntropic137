"""List Systems query.

Query to list systems, optionally filtered by organization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ListSystemsQuery:
    """Query to list systems.

    Attributes:
        organization_id: Optional organization ID to filter by.
        query_id: Unique identifier for this query.
    """

    organization_id: str | None = None
    query_id: str = field(default_factory=lambda: str(uuid4()))
