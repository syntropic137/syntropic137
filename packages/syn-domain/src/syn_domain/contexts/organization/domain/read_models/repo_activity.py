"""Repo activity read model.

Per-repo execution timeline entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from syn_shared.display import resolve_duration_seconds

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class RepoActivityEntry:
    """Single entry in a repo's execution timeline.

    Attributes:
        execution_id: Workflow execution ID.
        workflow_id: Workflow template ID.
        workflow_name: Human-readable workflow name.
        status: Execution status (running, completed, failed, cancelled).
        started_at: ISO timestamp of execution start, or None if unrecorded.
        completed_at: ISO timestamp of execution completion, None while running.
        duration_seconds: Seconds the execution has run, or None if unknown.
        trigger_source: What triggered the execution (webhook, manual, schedule).
    """

    execution_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    status: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    trigger_source: str = ""

    @classmethod
    def from_execution_row(cls, row: Mapping[str, Any]) -> RepoActivityEntry:
        """Build a timeline entry from a ``workflow_executions`` projection row.

        Every timeline surface (repo activity, system activity, system history)
        reads the same rows and shows the same entry, so they build it the same
        way, here. They each had their own copy of this, and each copy answered
        "how long did it take" with 0.0 for an execution that was still running
        - a number that reads as "finished instantly" for something that has
        not finished at all. The duration comes from the one rule every read
        surface uses, which returns None when it genuinely does not know.
        """
        status = str(row.get("status", ""))
        started_at = row.get("started_at")
        completed_at = row.get("completed_at")
        return cls(
            execution_id=str(row.get("workflow_execution_id", "")),
            workflow_id=str(row.get("workflow_id", "")),
            workflow_name=str(row.get("workflow_name", "")),
            status=status,
            started_at=_as_text(started_at),
            completed_at=_as_text(completed_at),
            duration_seconds=resolve_duration_seconds(
                status, started_at=started_at, completed_at=completed_at
            ),
            trigger_source=str(row.get("trigger_source", "")),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RepoActivityEntry:
        """Create from dictionary data."""
        return cls(
            execution_id=data.get("execution_id", ""),
            workflow_id=data.get("workflow_id", ""),
            workflow_name=data.get("workflow_name", ""),
            status=data.get("status", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            duration_seconds=data.get("duration_seconds"),
            trigger_source=data.get("trigger_source", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "trigger_source": self.trigger_source,
        }


def _as_text(value: object | None) -> str | None:
    """Render a stored timestamp as text, keeping "absent" absent.

    ``str(None)`` is the string ``"None"``, which is not a timestamp and is not
    empty either: passed to the API's ``datetime | None`` field it failed
    validation, so asking a repo for its activity while any of its executions
    was still running returned a 500 rather than the running execution.
    """
    return None if value is None else str(value)
