"""List Triggers query.

Query to list registered trigger rules with optional filters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ListTriggersQuery:
    """Query to list trigger rules.

    Attributes:
        repository: Filter by repository (owner/repo). None for all.
        status: Filter by status (active/paused/deleted). None for all.
        query_id: Unique identifier for this query.
    """

    repository: str | None = None
    status: str | None = None
    query_id: str = field(default_factory=lambda: str(uuid4()))
