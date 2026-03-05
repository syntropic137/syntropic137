"""List Organizations query.

Query to list all organizations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ListOrganizationsQuery:
    """Query to list organizations.

    Attributes:
        query_id: Unique identifier for this query.
    """

    query_id: str = field(default_factory=lambda: str(uuid4()))
