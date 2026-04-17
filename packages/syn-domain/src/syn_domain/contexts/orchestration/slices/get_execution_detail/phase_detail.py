"""Typed phase detail for execution projection.

Lane 1 domain truth — tokens only. Cost is Lane 2 telemetry and is merged in
at the API boundary from the execution_cost projection (#695).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PhaseDetail:
    """Typed representation of a phase within an execution."""

    phase_id: str
    name: str
    status: str = "pending"
    session_id: str | None = None
    artifact_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None

    @classmethod
    def running(
        cls,
        phase_id: str,
        name: str,
        *,
        session_id: str | None = None,
        started_at: str | None = None,
    ) -> PhaseDetail:
        """Create a phase in running state."""
        return cls(
            phase_id=phase_id,
            name=name,
            status="running",
            session_id=session_id,
            started_at=started_at,
        )

    @classmethod
    def completed(cls, phase_id: str, name: str, event_data: dict[str, Any]) -> PhaseDetail:
        """Create a completed phase from event data."""
        return cls(
            phase_id=phase_id,
            name=name,
            status="completed",
            session_id=event_data.get("session_id"),
            artifact_id=event_data.get("artifact_id"),
            input_tokens=event_data.get("input_tokens", 0),
            output_tokens=event_data.get("output_tokens", 0),
            cache_creation_tokens=event_data.get("cache_creation_tokens", 0),
            cache_read_tokens=event_data.get("cache_read_tokens", 0),
            total_tokens=event_data.get("total_tokens", 0),
            duration_seconds=event_data.get("duration_seconds", 0.0),
            completed_at=event_data.get("completed_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for projection store."""
        return {
            "phase_id": self.phase_id,
            "name": self.name,
            "status": self.status,
            "session_id": self.session_id,
            "artifact_id": self.artifact_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "total_tokens": self.total_tokens,
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseDetail:
        """Create from dict."""
        return cls(
            phase_id=data.get("phase_id", ""),
            name=data.get("name", ""),
            status=data.get("status", "pending"),
            session_id=data.get("session_id"),
            artifact_id=data.get("artifact_id"),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_creation_tokens=data.get("cache_creation_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
        )
