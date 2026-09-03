"""Typed phase entry for the workflow phase metrics read model.

Lane 1 domain truth - tokens only. Cost is Lane 2 telemetry and is merged in
at the API boundary from the execution_cost projection (#695).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from syn_shared.display import resolve_duration_seconds

if TYPE_CHECKING:
    from collections.abc import Mapping

StoredPhase = dict[str, str | int | float | None]
"""The stored shape of one phase. Narrow on purpose: it is JSON in a store."""


@dataclass(frozen=True)
class PhaseMetricsEntry:
    """One phase of a workflow, totalled across every run of that phase.

    This projection is keyed by workflow_id, not by execution_id, so a phase
    that has run five times has one entry holding the sum of all five - the
    same way its token counts are sums. ``duration_seconds()`` answers in that
    same currency, which is why it is a method on this entry rather than a
    field a caller can read: the stored fields alone do not answer the
    question, and no caller should have to know how they combine.
    """

    phase_id: str
    phase_name: str
    status: str = "running"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    artifact_count: int = 0

    completed_seconds: float | None = None
    """Seconds accumulated by the runs of this phase that FINISHED.

    ``None`` means no run has recorded one yet - not zero. A phase that has
    only ever been started has an unknown settled duration, and 0.0 is a
    measurement: it reads as "finished instantly".
    """

    started_at: datetime | str | None = None
    """When the most recent run of this phase started.

    Only consulted while that run is still in flight; a terminal phase's
    elapsed time is whatever was recorded when it ended.
    """

    @classmethod
    def from_stored(cls, phase_id: str, data: Mapping[str, Any]) -> PhaseMetricsEntry:
        """Read one entry back out of the projection store."""
        return cls(
            phase_id=phase_id,
            phase_name=data.get("phase_name") or phase_id,
            status=data.get("status", "completed"),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            artifact_count=data.get("artifact_count", 0),
            completed_seconds=data.get("duration_seconds"),
            started_at=data.get("started_at"),
        )

    def to_stored(self) -> StoredPhase:
        """Render this entry back into the shape the projection store holds.

        ``phase_id`` is the key it is stored under, so it is not repeated in
        the value.
        """
        return {
            "phase_name": self.phase_name,
            "status": self.status,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "artifact_count": self.artifact_count,
            "duration_seconds": self.completed_seconds,
            "started_at": _as_stored_text(self.started_at),
        }

    def with_finished_run(self, seconds: float | None) -> PhaseMetricsEntry:
        """Fold one finished run's elapsed time into the settled total.

        ACCUMULATE, never assign: this projection aggregates by workflow_id
        across every execution, so assigning made a later run erase the
        workflow's history (#1036). An unrecorded duration contributes nothing
        and, crucially, does not turn an unmeasured phase into a measured zero.
        """
        if seconds is None:
            return self
        settled = self.completed_seconds
        return replace(self, completed_seconds=seconds if settled is None else settled + seconds)

    def duration_seconds(self, *, now: datetime | str | None = None) -> float | None:
        """How long this phase has run in total, or ``None`` if nothing knows.

        The total is the settled time of the runs that finished plus, when a
        run is in flight, its elapsed time at the moment of the read. Both
        parts can be unknown independently, so the answer is the sum of the
        parts that are known and ``None`` when none of them are - never 0.0,
        which is a measurement and reads as "finished instantly".

        Adding the in-flight part rather than reporting it alone is what keeps
        the number from going BACKWARDS when a phase is retried: the completed
        runs' time is already counted in the token totals beside it, and
        dropping it here would repeat, for the length of the retry, the same
        erasure the failed-phase accumulator exists to prevent (#1036).
        """
        in_flight = resolve_duration_seconds(self.status, started_at=self.started_at, now=now)
        known = [part for part in (self.completed_seconds, in_flight) if part is not None]
        return math.fsum(known) if known else None


def _as_stored_text(value: datetime | str | None) -> str | None:
    """Store a timestamp as text, keeping "not started" absent rather than "None"."""
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)
