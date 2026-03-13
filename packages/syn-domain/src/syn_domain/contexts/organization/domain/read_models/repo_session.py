"""Read model for repo-scoped session records."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RepoSessionRecord:
    """Lightweight session record for repo insight views."""

    id: str
    execution_id: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    agent_type: str = ""
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "agent_type": self.agent_type,
            "total_tokens": self.total_tokens,
            "total_cost_usd": str(self.total_cost_usd),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoSessionRecord:
        return cls(
            id=data.get("id", ""),
            execution_id=data.get("execution_id", ""),
            status=data.get("status", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            agent_type=data.get("agent_type", ""),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=Decimal(str(data.get("total_cost_usd", 0))),
        )
