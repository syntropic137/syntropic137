"""Get System Cost query.

Query to retrieve the cost breakdown for a system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetSystemCostQuery:
    """Query to get a system's cost breakdown.

    Attributes:
        system_id: System ID to retrieve costs for.
        window_hours: Time window for cost aggregation (default 720 = 30 days).
        query_id: Unique identifier for this query.
    """

    system_id: str
    window_hours: int = 720
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.system_id:
            raise ValueError("system_id is required")
