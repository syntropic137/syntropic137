"""System status read model.

Cross-repo health overview within a system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RepoStatusEntry:
    """Health status for a single repo within a system.

    Attributes:
        repo_id: RepoAggregate ID.
        repo_full_name: Full repository name.
        status: Health status ("healthy", "degraded", "failing", "inactive").
        success_rate: Recent success rate (0.0 to 1.0).
        active_executions: Number of currently running executions.
        last_execution_at: ISO timestamp of last execution.
    """

    repo_id: str = ""
    repo_full_name: str = ""
    status: str = "inactive"
    success_rate: float = 0.0
    active_executions: int = 0
    last_execution_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoStatusEntry:
        """Create from dictionary data."""
        return cls(
            repo_id=data.get("repo_id", ""),
            repo_full_name=data.get("repo_full_name", ""),
            status=data.get("status", "inactive"),
            success_rate=data.get("success_rate", 0.0),
            active_executions=data.get("active_executions", 0),
            last_execution_at=data.get("last_execution_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "repo_id": self.repo_id,
            "repo_full_name": self.repo_full_name,
            "status": self.status,
            "success_rate": self.success_rate,
            "active_executions": self.active_executions,
            "last_execution_at": self.last_execution_at,
        }


@dataclass(frozen=True)
class SystemStatus:
    """Cross-repo health overview within a system.

    Attributes:
        system_id: SystemAggregate ID.
        system_name: Human-readable system name.
        organization_id: Owning organization ID.
        overall_status: Aggregate health ("healthy", "degraded", "failing").
        total_repos: Number of repos in the system.
        healthy_repos: Number of healthy repos.
        degraded_repos: Number of degraded repos.
        failing_repos: Number of failing repos.
        repos: Per-repo status entries.
    """

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    overall_status: str = "healthy"
    total_repos: int = 0
    healthy_repos: int = 0
    degraded_repos: int = 0
    failing_repos: int = 0
    repos: list[RepoStatusEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemStatus:
        """Create from dictionary data."""
        repos_data = data.get("repos", [])
        repos = [RepoStatusEntry.from_dict(r) for r in repos_data]
        return cls(
            system_id=data.get("system_id", ""),
            system_name=data.get("system_name", ""),
            organization_id=data.get("organization_id", ""),
            overall_status=data.get("overall_status", "healthy"),
            total_repos=data.get("total_repos", 0),
            healthy_repos=data.get("healthy_repos", 0),
            degraded_repos=data.get("degraded_repos", 0),
            failing_repos=data.get("failing_repos", 0),
            repos=repos,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "system_id": self.system_id,
            "system_name": self.system_name,
            "organization_id": self.organization_id,
            "overall_status": self.overall_status,
            "total_repos": self.total_repos,
            "healthy_repos": self.healthy_repos,
            "degraded_repos": self.degraded_repos,
            "failing_repos": self.failing_repos,
            "repos": [r.to_dict() for r in self.repos],
        }
