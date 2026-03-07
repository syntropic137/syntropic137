"""Global overview read model.

All systems plus unassigned repos overview.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class SystemOverviewEntry:
    """Summary of a single system for global overview.

    Attributes:
        system_id: SystemAggregate ID.
        system_name: Human-readable system name.
        organization_id: Owning organization ID.
        organization_name: Owning organization name.
        repo_count: Number of repos in the system.
        overall_status: Aggregate health ("healthy", "degraded", "failing").
        active_executions: Number of currently running executions.
        total_cost_usd: Total cost for this system.
    """

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    organization_name: str = ""
    repo_count: int = 0
    overall_status: str = "healthy"
    active_executions: int = 0
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemOverviewEntry:
        """Create from dictionary data."""
        return cls(
            system_id=data.get("system_id", ""),
            system_name=data.get("system_name", ""),
            organization_id=data.get("organization_id", ""),
            organization_name=data.get("organization_name", ""),
            repo_count=data.get("repo_count", 0),
            overall_status=data.get("overall_status", "healthy"),
            active_executions=data.get("active_executions", 0),
            total_cost_usd=Decimal(str(data.get("total_cost_usd", 0))),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "system_id": self.system_id,
            "system_name": self.system_name,
            "organization_id": self.organization_id,
            "organization_name": self.organization_name,
            "repo_count": self.repo_count,
            "overall_status": self.overall_status,
            "active_executions": self.active_executions,
            "total_cost_usd": str(self.total_cost_usd),
        }


@dataclass(frozen=True)
class GlobalOverview:
    """All systems plus unassigned repos overview.

    Attributes:
        total_systems: Total number of systems across all organizations.
        total_repos: Total number of repos across all organizations.
        unassigned_repos: Number of repos not assigned to any system.
        total_active_executions: Currently running executions globally.
        total_cost_usd: Total cost across everything.
        systems: Per-system overview entries.
    """

    total_systems: int = 0
    total_repos: int = 0
    unassigned_repos: int = 0
    total_active_executions: int = 0
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    systems: list[SystemOverviewEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GlobalOverview:
        """Create from dictionary data."""
        return cls(
            total_systems=data.get("total_systems", 0),
            total_repos=data.get("total_repos", 0),
            unassigned_repos=data.get("unassigned_repos", 0),
            total_active_executions=data.get("total_active_executions", 0),
            total_cost_usd=Decimal(str(data.get("total_cost_usd", 0))),
            systems=[SystemOverviewEntry.from_dict(s) for s in data.get("systems", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "total_systems": self.total_systems,
            "total_repos": self.total_repos,
            "unassigned_repos": self.unassigned_repos,
            "total_active_executions": self.total_active_executions,
            "total_cost_usd": str(self.total_cost_usd),
            "systems": [s.to_dict() for s in self.systems],
        }
