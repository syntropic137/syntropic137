"""System summary read model.

Represents the current state of a system, projected from events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SystemSummary:
    """Read model for a system summary.

    Attributes:
        system_id: Unique identifier for the system.
        organization_id: ID of the organization this system belongs to.
        name: Human-readable name.
        description: Optional description of the system.
        created_by: User or agent that created the system.
        created_at: When the system was created.
        repo_count: Number of repositories in this system.
        is_deleted: Whether the system has been soft-deleted.
    """

    system_id: str
    organization_id: str
    name: str
    description: str = ""
    created_by: str = ""
    created_at: datetime | None = None
    repo_count: int = 0
    is_deleted: bool = False
