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
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterable


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

    sequence: int
    """The event's position in the workflow's stream: its identity and its order."""
    definition_version: str | None
    """The package version, else the source digest, as a run records it; None if neither."""
    changed_at: str
    """ISO 8601 UTC: when the store recorded the change."""
    kind: DefinitionChangeKind


class WorkflowDefinitionHistory(BaseModel):
    """Every definition change of one workflow, in stream order. Also the stored document.

    Stream order (``sequence``) is the order of record, never the recorded
    time: events committed together share a millisecond, and a store's clock
    can step backwards, so time neither identifies a change nor orders them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str
    changes: tuple[WorkflowDefinitionChange, ...] = ()

    def with_change(self, change: WorkflowDefinitionChange) -> WorkflowDefinitionHistory:
        """This history plus ``change``, kept in stream order; unchanged if already in it.

        A redelivered or replayed event has the same stream position, so it is
        recognised by that and not counted twice.
        """
        if any(c.sequence == change.sequence for c in self.changes):
            return self
        changes = tuple(sorted((*self.changes, change), key=lambda c: c.sequence))
        return self.model_copy(update={"changes": changes})

    def version_at(self, at: datetime) -> str | None:
        """The version current at ``at``: see ``version_at`` (module function)."""
        return version_at(
            ((datetime.fromisoformat(c.changed_at), c.definition_version) for c in self.changes),
            at,
        )

    @property
    def current_version(self) -> str | None:
        return self.changes[-1].definition_version if self.changes else None


def version_at[V](changes: Iterable[tuple[datetime, V]], at: datetime) -> V | None:
    """The version current at ``at``, from ``(changed_at, version)`` pairs in stream order.

    Defined as: of the changes recorded at or before ``at``, the one latest in
    the stream. Times need not be monotonic in the stream, so every change is
    considered; stopping at the first later time would miss an earlier-dated
    change recorded after it.
    """
    current: V | None = None
    for changed_at, version in changes:
        if changed_at <= at:
            current = version
    return current
