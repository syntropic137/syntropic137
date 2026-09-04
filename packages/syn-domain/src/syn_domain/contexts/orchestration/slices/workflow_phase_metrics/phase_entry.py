"""Typed phase entry for the workflow phase metrics read model.

Lane 1 domain truth - tokens only. Cost is Lane 2 telemetry and is merged in
at the API boundary from the execution_cost projection (#695).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from syn_shared.display import compute_duration_seconds, resolve_duration_seconds

if TYPE_CHECKING:
    from collections.abc import Mapping

StoredRunStarts = dict[str, str | None]
"""When each execution still running a phase started it, keyed by execution id."""

StoredPhase = dict[str, str | int | float | StoredRunStarts | None]
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

    The runs themselves are tracked one per execution, because four to six
    executions of the same workflow are routinely in flight at once. Holding a
    single "started at T, status S" for the phase could not represent that:
    whichever execution finished first marked the shared phase terminal, so
    ``GET /metrics`` reported a phase as completed while other executions were
    still running it, and their elapsed time vanished from the total.
    """

    phase_id: str
    phase_name: str
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

    settled_status: str = "completed"
    """How the most recent run of this phase ENDED.

    Read it through ``status``, never directly: while any execution is still
    running the phase, what that run is doing outranks how an earlier one
    ended.
    """

    active_runs: Mapping[str, datetime | str | None] = field(default_factory=dict)
    """The executions running this phase right now, and when each started it.

    Keyed by execution id, so one execution finishing can neither close nor
    retime another execution's run of the same phase.
    """

    @property
    def status(self) -> str:
        """What this phase is doing, across every execution of its workflow.

        Any execution still running it makes the phase running: a phase
        aggregated over executions is only as terminal as its last live run.
        """
        return "running" if self.active_runs else self.settled_status

    @classmethod
    def from_stored(cls, phase_id: str, data: Mapping[str, Any]) -> PhaseMetricsEntry:
        """Read one entry back out of the projection store."""
        return cls(
            phase_id=phase_id,
            phase_name=data.get("phase_name") or phase_id,
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            artifact_count=data.get("artifact_count", 0),
            completed_seconds=data.get("duration_seconds"),
            settled_status=data.get("settled_status", "completed"),
            active_runs=data.get("active_runs") or {},
        )

    def to_stored(self) -> StoredPhase:
        """Render this entry back into the shape the projection store holds.

        ``phase_id`` is the key it is stored under, so it is not repeated in
        the value. ``status`` is not stored either: it is decided from the
        active runs at read time, and a stored copy would be a second answer
        to the same question, wrong from the moment a run opens or closes.
        """
        return {
            "phase_name": self.phase_name,
            "settled_status": self.settled_status,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "artifact_count": self.artifact_count,
            "duration_seconds": self.completed_seconds,
            "active_runs": {
                execution_id: _as_stored_text(started_at)
                for execution_id, started_at in self.active_runs.items()
            },
        }

    def with_run_started(
        self, execution_id: str, started_at: datetime | str | None
    ) -> PhaseMetricsEntry:
        """Open this execution's run of the phase.

        A start from an execution that already has a run open replaces its
        timestamp rather than adding a second one, so a re-delivered
        PhaseStarted cannot double-count the same run.
        """
        return replace(self, active_runs={**self.active_runs, execution_id: started_at})

    def with_run_finished(
        self,
        execution_id: str,
        *,
        status: str,
        recorded_seconds: float | None = None,
        ended_at: datetime | str | None = None,
    ) -> PhaseMetricsEntry:
        """Close this execution's run and fold its elapsed time into the total.

        Only this execution's run is closed. Every other execution's run stays
        open, which is what keeps a phase that four executions are running from
        going terminal the moment the first of them finishes.

        ``status`` is how THIS run ended, and must be terminal. How long it ran
        is decided by ``resolve_duration_seconds``, the same rule every read
        surface uses: the duration recorded at completion if there is one,
        otherwise the span from this run's own start to ``ended_at``.

        The elapsed time ACCUMULATES, never assigns: this projection aggregates
        by workflow_id across every execution, so assigning made a later run
        erase the workflow's history (#1036). An unknown duration contributes
        nothing and, crucially, does not turn an unmeasured phase into a
        measured zero.
        """
        seconds = resolve_duration_seconds(
            status,
            started_at=self.active_runs.get(execution_id),
            completed_at=ended_at,
            recorded_seconds=recorded_seconds,
        )
        settled = self.completed_seconds
        if seconds is not None:
            settled = seconds if settled is None else settled + seconds
        return replace(
            self,
            active_runs={
                other: started_at
                for other, started_at in self.active_runs.items()
                if other != execution_id
            },
            completed_seconds=settled,
            settled_status=status,
        )

    def duration_seconds(self, *, now: datetime | str | None = None) -> float | None:
        """How long this phase has run in total, or ``None`` if nothing knows.

        The total is the settled time of the runs that finished plus, for every
        run still in flight, its elapsed time at the moment of the read. Each
        part can be unknown independently, so the answer is the sum of the
        parts that are known and ``None`` when none of them are - never 0.0,
        which is a measurement and reads as "finished instantly".

        Live runs are summed rather than picked between for the same reason the
        settled ones are: this is the phase's total across the workflow's
        executions, in the same currency as the token counts beside it. Two
        executions five minutes into the same phase have cost ten phase-minutes.

        Adding the in-flight part rather than reporting it alone is what keeps
        the number from going BACKWARDS when a phase is retried: the completed
        runs' time is already counted in the token totals beside it, and
        dropping it here would repeat, for the length of the retry, the same
        erasure the failed-phase accumulator exists to prevent (#1036).
        """
        in_flight = (
            compute_duration_seconds(started_at, now=now)
            for started_at in self.active_runs.values()
        )
        known = [part for part in (self.completed_seconds, *in_flight) if part is not None]
        return math.fsum(known) if known else None


def _as_stored_text(value: datetime | str | None) -> str | None:
    """Store a timestamp as text, keeping "not started" absent rather than "None"."""
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)
