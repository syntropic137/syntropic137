"""Get Trigger History query.

Query to retrieve the execution history for a trigger rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class GetTriggerHistoryQuery:
    """Query to get trigger execution history.

    Attributes:
        trigger_id: ID of the trigger rule.
        limit: Maximum number of history entries to return.
        query_id: Unique identifier for this query.
    """

    trigger_id: str
    limit: int = 50
    query_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the query."""
        if not self.trigger_id:
            raise ValueError("trigger_id is required")
