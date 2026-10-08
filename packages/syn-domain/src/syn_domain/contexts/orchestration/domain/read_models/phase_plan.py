"""Every phase a run declared, each with where it stands (feedback cee46909).

The detail read model only learns of a phase when it starts, so a timeline
drawn from it shows the work done and hides the work left. This answers the
other question: of the phases the run set out to do, which ran here, which it
took over from the run it resumed, which a review made unnecessary, and which
are still to come.

The declared phases are read off the same `WorkflowExecutionStarted` that
states ``total_phases``, so the plan and the progress denominator count the
same list (feedback 9a95d8f7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
        PhaseExecutionDetail,
    )

PENDING = "pending"
"""Declared, not yet started, and still possible."""

SKIPPED = "skipped"
"""A review verdict made it unnecessary; it will never run (PC-63)."""

INHERITED = "inherited"
"""Completed by the run this one resumed, so not run here (ADR-014 s7)."""

_STATUS_DISPLAY = {
    PENDING: "Pending",
    SKIPPED: "Skipped (not needed)",
    INHERITED: "Inherited (completed earlier)",
}


@dataclass(frozen=True)
class DeclaredPhase:
    """One phase as the run's start event declared it."""

    phase_id: str
    name: str
    order: int


@dataclass(frozen=True)
class PlannedPhase:
    """A declared phase and where it stands in this run."""

    phase_id: str
    name: str
    status: str
    """``pending``, ``skipped``, ``inherited``, or the status of the phase as it
    ran here (``running``, ``completed``, ``failed``, ...)."""

    @property
    def status_display(self) -> str:
        """The status in words, e.g. ``Skipped (not needed)``."""
        return _STATUS_DISPLAY.get(self.status) or self.status.replace("_", " ").capitalize()


def plan_phases(
    declared: Sequence[DeclaredPhase],
    started: Sequence[PhaseExecutionDetail],
    skipped_phase_ids: Iterable[str],
    inherited_phase_ids: Iterable[str],
) -> tuple[PlannedPhase, ...]:
    """Every declared phase in order, then any started phase none declared.

    A phase that started here reports its own status. A run whose start event
    declared nothing (written before ISS-196) has only its started phases to
    show, which is all anything knew about it.
    """
    ran = {p.workflow_phase_id: p for p in started}
    skipped = set(skipped_phase_ids)
    inherited = set(inherited_phase_ids)

    def status_of(phase_id: str) -> str:
        if phase_id in ran:
            return ran[phase_id].status
        if phase_id in inherited:
            return INHERITED
        if phase_id in skipped:
            return SKIPPED
        return PENDING

    in_order = sorted(declared, key=lambda d: d.order)
    planned = [PlannedPhase(d.phase_id, d.name, status_of(d.phase_id)) for d in in_order]
    known = {d.phase_id for d in in_order}
    planned += [
        PlannedPhase(p.workflow_phase_id, p.name, p.status)
        for p in started
        if p.workflow_phase_id not in known
    ]
    return tuple(planned)
