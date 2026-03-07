"""Get System Patterns query.

Query to retrieve recurring failure and cost patterns for a system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetSystemPatternsQuery:
    """Query to get a system's recurring failure and cost patterns.

    Attributes:
        system_id: System ID to analyze patterns for.
        window_hours: Time window for pattern analysis (default 168 = 7 days).
        query_id: Unique identifier for this query.
    """

    system_id: str
    window_hours: int = 168
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.system_id:
            raise ValueError("system_id is required")
