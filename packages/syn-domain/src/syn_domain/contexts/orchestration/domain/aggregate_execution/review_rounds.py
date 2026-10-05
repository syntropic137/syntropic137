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
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
    ReviewVerdict,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class NextPhase:
    """The phase to run next, and the phases that will never run because of it."""

    phase: PhaseDefinition
    skipped: tuple[PhaseDefinition, ...] = field(default=())


def next_phase(
    phase_definitions: Sequence[PhaseDefinition],
    completed_order: int,
    verdict: ReviewVerdict | None,
) -> NextPhase | None:
    """What runs after the phase at ``completed_order``, or None if it was the last.

    ``phase_definitions`` is trusted to be sorted by order, which
    `replay.parse_phase_definitions` guarantees.
    """
    remaining = [p for p in phase_definitions if p.order > completed_order]
    if not remaining:
        return None
    if verdict is ReviewVerdict.CERTIFIED:
        return NextPhase(phase=remaining[-1], skipped=tuple(remaining[:-1]))
    return NextPhase(phase=remaining[0])
