"""Read model for dashboard metrics.

Lane 1 domain truth: workflow template and artifact counts. Everything else
GET /metrics reports comes from a list read model or the canonical usage totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict


class TemplateCreatedRef(BaseModel):
    """The one field the workflow count needs from a template's creation payload (#641).

    Not WorkflowTemplateCreatedEvent itself: the in-process map also routes the
    legacy WorkflowCreated to the same handler, whose payload is shaped
    differently, so every other field is ignored rather than validated.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    workflow_id: str = ""


class ArtifactCreatedRef(BaseModel):
    """The one field the byte total needs from an ArtifactCreated payload (#2274).

    Not ArtifactCreatedEvent itself: only ``size_bytes`` is read here, so a
    stored payload that lacks the key counts as 0 bytes instead of failing
    validation of fields this read model never uses.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    size_bytes: int = 0


@dataclass(frozen=True)
class DashboardMetrics:
    """Read model for dashboard metrics.

    Only the counts no list read model pages through. Execution status counts,
    sessions, tokens and cost are read by GET /metrics from their own lists and
    the canonical usage totals (#1843, #932), so they are not kept here (#2272).
    """

    total_workflows: int = 0
    """Workflow templates that are not archived (matches GET /workflows total)."""

    total_artifacts: int = 0
    """Total number of artifacts."""

    total_artifact_bytes: int = 0
    """Total artifact size in bytes."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DashboardMetrics:
        """Create from dictionary data."""
        return cls(
            total_workflows=data.get("total_workflows", 0),
            total_artifacts=data.get("total_artifacts", 0),
            total_artifact_bytes=data.get("total_artifact_bytes", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "total_workflows": self.total_workflows,
            "total_artifacts": self.total_artifacts,
            "total_artifact_bytes": self.total_artifact_bytes,
        }
