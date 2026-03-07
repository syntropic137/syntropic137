"""Get Global Cost query.

Query to retrieve the cost breakdown across all systems and repos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetGlobalCostQuery:
    """Query to get the global cost breakdown.

    Attributes:
        window_hours: Time window for cost aggregation (default 720 = 30 days).
        query_id: Unique identifier for this query.
    """

    window_hours: int = 720
    query_id: str = field(default_factory=lambda: str(uuid4()))
