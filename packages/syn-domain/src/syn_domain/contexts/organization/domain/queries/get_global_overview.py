"""Get Global Overview query.

Query to retrieve the global overview of all systems and repos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetGlobalOverviewQuery:
    """Query to get the global overview.

    Attributes:
        query_id: Unique identifier for this query.
    """

    query_id: str = field(default_factory=lambda: str(uuid4()))
