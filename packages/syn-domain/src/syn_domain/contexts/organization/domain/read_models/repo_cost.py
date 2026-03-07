"""Repo cost read model.

Per-repo cost breakdown by workflow, model, and tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RepoCost:
    """Per-repo cost breakdown.

    Attributes:
        repo_id: RepoAggregate ID.
        repo_full_name: Full repository name (e.g. "owner/repo").
        total_cost_usd: Total cost across all executions.
        total_tokens: Total tokens used.
        total_input_tokens: Total input tokens.
        total_output_tokens: Total output tokens.
        cost_by_workflow: Cost breakdown by workflow ID (Decimal values).
        cost_by_model: Cost breakdown by model name (Decimal values).
        execution_count: Number of executions contributing to cost.
    """

    repo_id: str = ""
    repo_full_name: str = ""
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_by_workflow: dict[str, Decimal] = field(default_factory=dict)
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    execution_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoCost:
        """Create from dictionary data."""
        return cls(
            repo_id=data.get("repo_id", ""),
            repo_full_name=data.get("repo_full_name", ""),
            total_cost_usd=Decimal(str(data.get("total_cost_usd", 0))),
            total_tokens=data.get("total_tokens", 0),
            total_input_tokens=data.get("total_input_tokens", 0),
            total_output_tokens=data.get("total_output_tokens", 0),
            cost_by_workflow={
                k: Decimal(str(v)) for k, v in data.get("cost_by_workflow", {}).items()
            },
            cost_by_model={
                k: Decimal(str(v)) for k, v in data.get("cost_by_model", {}).items()
            },
            execution_count=data.get("execution_count", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "repo_id": self.repo_id,
            "repo_full_name": self.repo_full_name,
            "total_cost_usd": str(self.total_cost_usd),
            "total_tokens": self.total_tokens,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "cost_by_workflow": {k: str(v) for k, v in self.cost_by_workflow.items()},
            "cost_by_model": {k: str(v) for k, v in self.cost_by_model.items()},
            "execution_count": self.execution_count,
        }
