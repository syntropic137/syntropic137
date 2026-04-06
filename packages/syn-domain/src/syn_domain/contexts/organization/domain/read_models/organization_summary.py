"""Organization summary read model.

Represents the current state of an organization, projected from events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class OrganizationSummary:
    """Read model for an organization summary.

    Attributes:
        organization_id: Unique identifier for the organization.
        name: Human-readable name.
        slug: URL-safe slug.
        created_by: User or agent that created the organization.
        created_at: When the organization was created.
        system_count: Number of systems in this organization.
        repo_count: Number of repositories in this organization.
        is_deleted: Whether the organization has been soft-deleted.
    """

    organization_id: str
    name: str
    slug: str
    created_by: str = ""
    created_at: datetime | None = None
    system_count: int = 0
    repo_count: int = 0
    is_deleted: bool = False
