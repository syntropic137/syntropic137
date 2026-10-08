"""When a workflow's definition changed, so a trend chart can annotate it (#1788).

A run records the version it launched from (``workflow_version``). That says
which definition a run used, not WHEN the definition changed: the first run of
a new version can come days after the install. These records come from the
template's own stream: created, reinstalled (``WorkflowTemplateUpdated``) and
phase-edited (``WorkflowPhaseUpdated``), each dated by when the store recorded
the event.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DefinitionChangeKind(StrEnum):
    """What changed the definition."""

    CREATED = "created"
    UPDATED = "updated"
    """Reinstalled or replaced wholesale."""
    PHASE_UPDATED = "phase_updated"
    """One phase's prompt or config edited in place; the version does not move."""


class WorkflowDefinitionChange(BaseModel):
    """One change to a workflow's definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_version: str | None
    """The package version, else the source digest, as a run records it; None if neither."""
    changed_at: str
    """ISO 8601 UTC: when the store recorded the change."""
    kind: DefinitionChangeKind


class WorkflowDefinitionHistory(BaseModel):
    """Every definition change of one workflow, oldest first. Also the stored document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str
    changes: tuple[WorkflowDefinitionChange, ...] = ()

    def with_change(self, change: WorkflowDefinitionChange) -> WorkflowDefinitionHistory:
        """This history plus ``change``; unchanged when ``change`` is already in it.

        Redelivery of the same event carries the same recorded time and kind,
        so it is recognised by those and not counted twice.
        """
        if any((c.changed_at, c.kind) == (change.changed_at, change.kind) for c in self.changes):
            return self
        return self.model_copy(update={"changes": (*self.changes, change)})

    def version_at(self, at: datetime) -> str | None:
        """The version of the last change recorded at or before ``at``."""
        current = None
        for change in self.changes:
            if datetime.fromisoformat(change.changed_at) > at:
                break
            current = change.definition_version
        return current

    @property
    def current_version(self) -> str | None:
        return self.changes[-1].definition_version if self.changes else None
