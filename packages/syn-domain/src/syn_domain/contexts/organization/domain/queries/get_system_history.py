"""Get System History query.

Query to retrieve historical system status snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetSystemHistoryQuery:
    """Query to get a system's historical status snapshots.

    Attributes:
        system_id: System ID to retrieve history for.
        window_hours: Time window for history (default 168 = 7 days).
        limit: Maximum number of snapshots to return.
        query_id: Unique identifier for this query.
    """

    system_id: str
    window_hours: int = 168
    limit: int = 50
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.system_id:
            raise ValueError("system_id is required")
