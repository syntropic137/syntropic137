"""Get System query.

Query to retrieve the current state of a system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetSystemQuery:
    """Query to get a system by ID.

    Attributes:
        system_id: System ID to retrieve.
        query_id: Unique identifier for this query.
    """

    system_id: str
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.system_id:
            raise ValueError("system_id is required")
