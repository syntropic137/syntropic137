"""A resumed run counts the phases it inherited, once, in both read models.

A resume takes over its parent's completed prefix without a `PhaseCompleted`
for any of it (ADR-014 s7). Counting from zero made a run resumed at phase 3 of
10 read "phase 1 of up to 10". Every start here is the event the real producer
writes: the prefix from `resume_rules.completed_prefix`, the start from
`resume_start.resume_started_event`, and each skip from `review_rounds.next_phase`.
Each case also replays the same events into empty stores and requires the same
rows, because a rebuild is how every deployment reaches this projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartResumeCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.resume_rules import (
    completed_prefix,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.resume_start import (
    resume_started_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.review_rounds import (
    next_phase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    PhaseDefinition,
    ResumeOrigin,
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from pydantic import JsonValue

    from syn_domain.contexts.orchestration.domain.read_models.phase_progress import (
        PhaseProgress,
    )

pytestmark = pytest.mark.unit

_PHASE_IDS = [
    "premise",
    "implement",
    "verify",
    "fix",
    "reverify",
    "fix_2",
    "reverify_2",
    "fix_3",
    "reverify_3",
    "finalize_pr",
]
_IMPLEMENT_V3 = [
    PhaseDefinition(phase_id=phase_id, name=phase_id, order=order)
    for order, phase_id in enumerate(_PHASE_IDS, start=1)
]
_PINNED = [
    ExecutablePhase(
        phase_id=phase_id,
        name=phase_id,
        order=order,
        agent_config=AgentConfiguration(),
        prompt_template=phase_id,
        output_artifact_types=(),
        timeout_seconds=1800,
    )
    for order, phase_id in enumerate(_PHASE_IDS, start=1)
]
_PARENT = "exec-parent"
_CHILD = "exec-child"
_WORKFLOW = "sdlc-implement-v3"


@dataclass(frozen=True)
class _Applied:
    """One event as the coordinator hands it to a projection handler."""

    handler: str
    payload: dict[str, JsonValue]


@dataclass
class _Stream:
    """The child's events, in order, so they can be applied again from empty."""

    events: list[_Applied] = field(default_factory=list)
    completed: int = 0

    def start(self, completed_in_parent: set[str]) -> None:
        """Start the child the way a resume does, from what the parent completed."""
        inherited, resume_phase_id = completed_prefix(
            _IMPLEMENT_V3,
            completed_in_parent,
            {},
            execution_id=_PARENT,
            phase_owners={},
        )
        assert resume_phase_id is not None
        started = resume_started_event(
            StartResumeCommand(
                execution_id=_CHILD,
                workflow_id=_WORKFLOW,
                workflow_name="implement-v3",
                inputs={},
                pinned_phases=_PINNED,
                source_commits=[],
                resumed_from=ResumeOrigin(
                    parent_execution_id=_PARENT,
                    inherited_phases=inherited,
                    resume_phase_id=resume_phase_id,
                ),
            )
        )
        # The aggregate seeds its own count with the prefix, so the terminal
        # event's total includes it (`WorkflowExecutionAggregate._inherit`).
        self.completed = len(inherited)
        self.events.append(
            _Applied("on_workflow_execution_started", started.model_dump(mode="json"))
        )

    def start_fresh(self) -> None:
        self.events.append(
            _Applied(
                "on_workflow_execution_started",
                {
                    "execution_id": _CHILD,
                    "workflow_id": _WORKFLOW,
                    "workflow_name": "implement-v3",
                    "started_at": "2026-10-07T00:00:00+00:00",
                    "total_phases": len(_IMPLEMENT_V3),
                },
            )
        )

    def complete(self, phase_id: str, verdict: ReviewVerdict | None = None) -> None:
        phase = next(p for p in _IMPLEMENT_V3 if p.phase_id == phase_id)
        self.events.append(
            _Applied(
                "on_phase_completed",
                {"execution_id": _CHILD, "phase_id": phase_id, "duration_seconds": 1.0},
            )
        )
        self.completed += 1
        decided = next_phase(_IMPLEMENT_V3, phase.order, verdict)
        if decided is not None:
            event = decided.event(
                workflow_id=_WORKFLOW, execution_id=_CHILD, completed_phase_id=phase_id
            )
            self.events.append(_Applied("on_next_phase_ready", event.model_dump(mode="json")))

    def finish(self) -> None:
        self.events.append(
            _Applied(
                "on_workflow_completed",
                {
                    "execution_id": _CHILD,
                    "completed_at": datetime(2026, 10, 7, 1, tzinfo=UTC).isoformat(),
                    "completed_phases": self.completed,
                    "total_phases": len(_IMPLEMENT_V3),
                },
            )
        )

    async def progress(self) -> PhaseProgress:
        """Progress from empty stores, required equal across list, detail, and a replay."""
        first = await self._apply_from_empty()
        replayed = await self._apply_from_empty()
        assert first == replayed
        return first[0]

    async def _apply_from_empty(
        self,
    ) -> tuple[PhaseProgress, dict[str, object], dict[str, object]]:
        listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
        detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        for applied in self.events:
            for projection in (listing, detail):
                await getattr(projection, applied.handler)(applied.payload)
        summary = await listing.get_by_id(_CHILD)
        detailed = await detail.get_by_id(_CHILD)
        assert summary is not None
        assert detailed is not None
        assert summary.phase_progress == detailed.phase_progress
        return summary.phase_progress, summary.to_dict(), detailed.to_dict()


class TestResumedPhaseProgress:
    async def test_a_fresh_run_inherits_nothing(self) -> None:
        stream = _Stream()
        stream.start_fresh()
        stream.complete("premise")

        progress = await stream.progress()

        assert progress.completed == 1
        assert progress.display == "phase 2 of up to 10"

    async def test_resumed_at_phase_three_counts_the_two_it_inherited(self) -> None:
        stream = _Stream()
        stream.start({"premise", "implement"})

        progress = await stream.progress()

        assert progress.completed == 2
        assert progress.remaining_possible == 8
        assert progress.display == "phase 3 of up to 10"

    async def test_resumed_then_completing_counts_on_from_the_prefix(self) -> None:
        stream = _Stream()
        stream.start({"premise", "implement"})
        stream.complete("verify", ReviewVerdict.CERTIFIED)

        progress = await stream.progress()

        assert (progress.completed, progress.skipped, progress.possible) == (3, 6, 4)
        assert progress.display == "phase 4 of up to 4 (6 phases not needed)"

    async def test_resumed_after_a_round_then_certified_inherits_and_skips(self) -> None:
        # The parent ran through its first repair round and failed; the child
        # inherits those five, runs round two and is certified there.
        stream = _Stream()
        stream.start({"premise", "implement", "verify", "fix", "reverify"})
        stream.complete("fix_2")
        stream.complete("reverify_2", ReviewVerdict.CERTIFIED)
        stream.complete("finalize_pr")
        stream.finish()

        progress = await stream.progress()

        assert (progress.completed, progress.skipped, progress.possible) == (8, 2, 8)
        assert progress.display == "8 of 8 (2 phases not needed)"

    async def test_the_terminal_total_restates_the_prefix_without_adding_it_again(
        self,
    ) -> None:
        stream = _Stream()
        stream.start({"premise", "implement"})
        for phase_id in _PHASE_IDS[2:]:
            stream.complete(phase_id, ReviewVerdict.BLOCKED if "verify" in phase_id else None)
        stream.finish()

        progress = await stream.progress()

        assert (progress.completed, progress.possible) == (10, 10)
        assert progress.display == "10 of 10"
