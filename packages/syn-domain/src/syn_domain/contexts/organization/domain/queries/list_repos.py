"""List Repos query.

Query to list repositories, optionally filtered by organization, system, or provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ListReposQuery:
    """Query to list repositories.

    Attributes:
        organization_id: Optional organization ID to filter by.
        system_id: Optional system ID to filter by.
        provider: Optional provider to filter by (github/gitea/gitlab).
        unassigned: When True, only return repos not assigned to any system.
        query_id: Unique identifier for this query.
    """

    organization_id: str | None = None
    system_id: str | None = None
    provider: str | None = None
    unassigned: bool = False
    query_id: str = field(default_factory=lambda: str(uuid4()))
