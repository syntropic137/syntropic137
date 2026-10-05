"""Which phase runs after a phase completes, given what it concluded (PC-63).

The aggregate's sequencing rule, as a pure function of the phase definitions
and the completed phase's review verdict, so it is testable without building an
aggregate - the same split as `resume_rules`.

Order is the default: the next phase is the next one by `order`. A
``certified`` verdict is the one thing that overrides it. It ends the repair
loop, so every phase before the workflow's FINAL phase is skipped and the final
phase is next. That is how a workflow writes a bounded repair loop with no loop
construct: the rounds are ordinary phases in sequence, and a certification
jumps over the rounds it made unnecessary. ``blocked`` and no verdict at all
both advance by order - the next round, or the final phase once the rounds are
spent.

The final phase is never skipped, and a verdict reported BY the final phase
changes nothing: there is nothing after it to jump to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
    ReviewVerdict,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
        NextPhaseReadyEvent,
    )


@dataclass(frozen=True)
class NextPhase:
    """The phase to run next, and the phases that will never run because of it."""

    phase: PhaseDefinition
    skipped: tuple[PhaseDefinition, ...] = field(default=())

    def event(
        self, *, workflow_id: str, execution_id: str, completed_phase_id: str
    ) -> NextPhaseReadyEvent:
        """The `NextPhaseReady` that records this decision, skipped phases included."""
        from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
            NextPhaseReadyEvent,
        )

        return NextPhaseReadyEvent(
            workflow_id=workflow_id,
            execution_id=execution_id,
            completed_phase_id=completed_phase_id,
            next_phase_id=self.phase.phase_id,
            next_phase_order=self.phase.order,
            decided_at=datetime.now(UTC),
            skipped_phase_ids=[p.phase_id for p in self.skipped],
        )


@dataclass
class ReviewRecord:
    """The review verdicts an execution's stream holds - replayed state.

    A verdict is REPORTED when a phase's agent finishes and DECIDED ON when its
    artifacts are collected, two to-do items and possibly two processes, so it
    is kept here rather than passed along. Each agent run overwrites its
    phase's report, so a retry that says nothing does not inherit the
    abandoned attempt's verdict.
    """

    _reported: dict[str, ReviewVerdict | None] = field(default_factory=dict)
    #: The verdict of the last COLLECTED phase that reported one: how the run
    #: stands, and what `WorkflowCompleted` records it ended on.
    latest: ReviewVerdict | None = None

    def report(self, phase_id: str, verdict: ReviewVerdict | None) -> None:
        """A phase's agent run finished, saying ``verdict`` (or nothing)."""
        self._reported[phase_id] = verdict

    def of(self, phase_id: str) -> ReviewVerdict | None:
        """What this phase's latest run reported."""
        return self._reported.get(phase_id)

    def collect(self, phase_id: str) -> None:
        """This phase's output was stored; its verdict, if any, now stands."""
        verdict = self._reported.get(phase_id)
        if verdict is not None:
            self.latest = verdict


def next_phase(
    phase_definitions: Sequence[PhaseDefinition],
    completed_order: int | None,
    verdict: ReviewVerdict | None,
) -> NextPhase | None:
    """What runs after the phase at ``completed_order``, or None if it was the last.

    None too for a phase the definitions do not name: the aggregate does not
    sequence what it was not given.

    ``phase_definitions`` is trusted to be sorted by order, which
    `replay.parse_phase_definitions` guarantees.
    """
    if completed_order is None:
        return None
    remaining = [p for p in phase_definitions if p.order > completed_order]
    if not remaining:
        return None
    if verdict is ReviewVerdict.CERTIFIED:
        return NextPhase(phase=remaining[-1], skipped=tuple(remaining[:-1]))
    return NextPhase(phase=remaining[0])
