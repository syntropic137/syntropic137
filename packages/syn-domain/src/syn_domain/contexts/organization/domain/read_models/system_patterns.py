"""System patterns read model.

Recurring failure and cost patterns within a system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class FailurePattern:
    """A recurring failure pattern.

    Attributes:
        error_type: Error classification.
        error_message: Representative error message.
        occurrence_count: Number of times this pattern occurred.
        affected_repos: Repos where this pattern was seen.
        first_seen: ISO timestamp of first occurrence.
        last_seen: ISO timestamp of last occurrence.
    """

    error_type: str = ""
    error_message: str = ""
    occurrence_count: int = 0
    affected_repos: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailurePattern:
        """Create from dictionary data."""
        return cls(
            error_type=data.get("error_type", ""),
            error_message=data.get("error_message", ""),
            occurrence_count=data.get("occurrence_count", 0),
            affected_repos=data.get("affected_repos", []),
            first_seen=data.get("first_seen", ""),
            last_seen=data.get("last_seen", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "error_type": self.error_type,
            "error_message": self.error_message,
            "occurrence_count": self.occurrence_count,
            "affected_repos": list(self.affected_repos),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


@dataclass(frozen=True)
class CostOutlier:
    """An execution with unusually high cost.

    Attributes:
        execution_id: Workflow execution ID.
        repo_full_name: Repository full name.
        workflow_name: Workflow template name.
        cost_usd: Cost of the execution.
        median_cost_usd: Median cost for this workflow.
        deviation_factor: How many standard deviations above median.
        executed_at: ISO timestamp of execution.
    """

    execution_id: str = ""
    repo_full_name: str = ""
    workflow_name: str = ""
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    median_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    deviation_factor: float = 0.0
    executed_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostOutlier:
        """Create from dictionary data."""
        return cls(
            execution_id=data.get("execution_id", ""),
            repo_full_name=data.get("repo_full_name", ""),
            workflow_name=data.get("workflow_name", ""),
            cost_usd=Decimal(str(data.get("cost_usd", 0))),
            median_cost_usd=Decimal(str(data.get("median_cost_usd", 0))),
            deviation_factor=data.get("deviation_factor", 0.0),
            executed_at=data.get("executed_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "execution_id": self.execution_id,
            "repo_full_name": self.repo_full_name,
            "workflow_name": self.workflow_name,
            "cost_usd": str(self.cost_usd),
            "median_cost_usd": str(self.median_cost_usd),
            "deviation_factor": self.deviation_factor,
            "executed_at": self.executed_at,
        }


@dataclass(frozen=True)
class SystemPatterns:
    """Recurring failure and cost patterns within a system.

    Attributes:
        system_id: SystemAggregate ID.
        system_name: Human-readable system name.
        failure_patterns: Recurring failure patterns.
        cost_outliers: Executions with unusually high cost.
        analysis_window_hours: Time window used for pattern analysis.
    """

    system_id: str = ""
    system_name: str = ""
    failure_patterns: list[FailurePattern] = field(default_factory=list)
    cost_outliers: list[CostOutlier] = field(default_factory=list)
    analysis_window_hours: int = 168

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemPatterns:
        """Create from dictionary data."""
        return cls(
            system_id=data.get("system_id", ""),
            system_name=data.get("system_name", ""),
            failure_patterns=[
                FailurePattern.from_dict(p) for p in data.get("failure_patterns", [])
            ],
            cost_outliers=[CostOutlier.from_dict(o) for o in data.get("cost_outliers", [])],
            analysis_window_hours=data.get("analysis_window_hours", 168),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "system_id": self.system_id,
            "system_name": self.system_name,
            "failure_patterns": [p.to_dict() for p in self.failure_patterns],
            "cost_outliers": [o.to_dict() for o in self.cost_outliers],
            "analysis_window_hours": self.analysis_window_hours,
        }
