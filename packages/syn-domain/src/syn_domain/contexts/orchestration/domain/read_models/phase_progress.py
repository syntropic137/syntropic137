"""How far through its phases an execution is, said once for every client.

A workflow's phase count is not the number of phases a run will do. A review
that certifies skips the repair rounds after it (PC-63, `review_rounds.py`),
so `sdlc-implement-v3`, ten phases, finishes in six when the first reverify
certifies. Printing `completed/total` made that run read "6/10" - finished,
yet apparently four phases short - and a running one read "/10" when most
runs never use the later rounds.

So the denominator is what the run can still do: the defined phases less the
ones a decision has already ruled out. That number only shrinks, so a running
run says "of up to", and a finished one says how many were not needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    ResumeOrigin,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class PhaseProgress:
    """An execution's phase progress, with skipped phases accounted for."""

    status: str
    """The execution's status, as its read model holds it."""

    completed: int
    """Phases that ran to completion."""

    skipped: int
    """Phases a review verdict made unnecessary; they will never run."""

    defined: int
    """Phases the workflow defines, as the run's start event stated."""

    @property
    def possible(self) -> int:
        """The most phases this run can complete: defined, less the skipped."""
        return max(self.defined - self.skipped, self.completed)

    @property
    def remaining_possible(self) -> int:
        """Phases that could still run. Zero once the run has ended."""
        if self.status in _ENDED:
            return 0
        return self.possible - self.completed

    @property
    def percent(self) -> int:
        """Completed as a share of what was possible, 0-100. A completed run is 100."""
        if self.status == ExecutionStatus.COMPLETED:
            return 100
        if self.possible == 0:
            return 0
        return round(100 * self.completed / self.possible)

    @property
    def display(self) -> str:
        """The progress in words, e.g. ``6 of 6 (4 phases not needed)``."""
        if self.status == ExecutionStatus.COMPLETED:
            return f"{self.completed} of {self.possible}{self._not_needed()}"
        if self.status in _ENDED:
            return f"{self.completed} of up to {self.possible}, {self.status}{self._not_needed()}"
        if self.status == ExecutionStatus.RUNNING and self.possible > 0:
            current = min(self.completed + 1, self.possible)
            return f"phase {current} of up to {self.possible}{self._not_needed()}"
        if self.completed == 0:
            return "not started"
        return f"{self.completed} of up to {self.possible}"

    def _not_needed(self) -> str:
        if self.skipped == 0:
            return ""
        noun = "phase" if self.skipped == 1 else "phases"
        return f" ({self.skipped} {noun} not needed)"


_ENDED = frozenset(
    {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.INTERRUPTED,
    }
)


def record_skips(recorded: Sequence[str], skipped: Sequence[str]) -> list[str]:
    """``recorded`` with ``skipped`` added, each phase once, in the order first seen.

    A set, not a running count, so a `NextPhaseReady` applied twice does not
    count its skips twice.
    """
    return list(dict.fromkeys([*recorded, *skipped]))


def inherited_phase_count(started: Mapping[str, object]) -> int:
    """Phases a resumed run took over completed from its parent, read off its start.

    A resume never emits `PhaseCompleted` for the prefix it inherits
    (ADR-014 s7), so a read model that counts from zero shows a run resumed at
    phase 3 of 10 as "phase 1". The aggregate seeds its own count the same way
    (`WorkflowExecutionAggregate._inherit`), so a terminal event's total, which already
    includes the prefix, restates this figure rather than adding to it.
    Zero for a fresh run.
    """
    origin = started.get("resumed_from")
    if origin is None:
        return 0
    return len(ResumeOrigin.model_validate(origin).inherited_phases)
