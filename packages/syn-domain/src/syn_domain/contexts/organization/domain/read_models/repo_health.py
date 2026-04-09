"""Repo health read model.

Per-repo health snapshot with success rate, trend, and windowed costs/tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RepoHealth:
    """Per-repo health snapshot.

    Attributes:
        repo_id: RepoAggregate ID.
        repo_full_name: Full repository name (e.g. "owner/repo").
        total_executions: Total number of executions for this repo.
        successful_executions: Number of successful executions.
        failed_executions: Number of failed executions.
        success_rate: Success rate as a fraction (0.0 to 1.0).
        trend: Health trend direction ("improving", "stable", "degrading").
        recent_cost_usd: Cost in current time window.
        window_tokens: Tokens used in current time window.
        last_execution_at: ISO timestamp of last execution.
    """

    repo_id: str = ""
    repo_full_name: str = ""
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    success_rate: float = 0.0
    trend: str = "stable"
    recent_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    window_tokens: int = 0
    last_execution_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoHealth:
        """Create from dictionary data."""
        return cls(
            repo_id=data.get("repo_id", ""),
            repo_full_name=data.get("repo_full_name", ""),
            total_executions=data.get("total_executions", 0),
            successful_executions=data.get("successful_executions", 0),
            failed_executions=data.get("failed_executions", 0),
            success_rate=data.get("success_rate", 0.0),
            trend=data.get("trend", "stable"),
            recent_cost_usd=Decimal(str(data.get("recent_cost_usd", 0))),
            window_tokens=data.get("window_tokens", 0),
            last_execution_at=data.get("last_execution_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "repo_id": self.repo_id,
            "repo_full_name": self.repo_full_name,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "success_rate": self.success_rate,
            "trend": self.trend,
            "recent_cost_usd": str(self.recent_cost_usd),
            "window_tokens": self.window_tokens,
            "last_execution_at": self.last_execution_at,
        }
