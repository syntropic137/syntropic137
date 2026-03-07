"""Get System Activity query.

Query to retrieve the execution timeline across a system's repos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetSystemActivityQuery:
    """Query to get a system's execution timeline across all repos.

    Attributes:
        system_id: System ID to retrieve activity for.
        limit: Maximum number of entries to return.
        offset: Number of entries to skip (for pagination).
        query_id: Unique identifier for this query.
    """

    system_id: str
    limit: int = 50
    offset: int = 0
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.system_id:
            raise ValueError("system_id is required")
