"""Get System Status query.

Query to retrieve the cross-repo health overview for a system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetSystemStatusQuery:
    """Query to get a system's cross-repo health overview.

    Attributes:
        system_id: System ID to retrieve status for.
        query_id: Unique identifier for this query.
    """

    system_id: str
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.system_id:
            raise ValueError("system_id is required")
