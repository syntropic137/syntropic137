"""Phase progress counts the repair rounds a review made unnecessary (PC-63).

`sdlc-implement-v3` defines ten phases, four of them repair rounds that a
certifying review skips. Before the read models consumed `NextPhaseReady`, a
run certified at its first review finished as "6/10". Each case here drives
BOTH execution read models with the skips the aggregate's own sequencing rule
(`next_phase`) produces, then reads progress back through each projection's
query, so a skip dropped by a handler or a row's `from_dict` fails here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.review_rounds import (
    next_phase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.read_models.phase_progress import (
        PhaseProgress,
    )

pytestmark = pytest.mark.unit

_IMPLEMENT_V3 = [
    PhaseDefinition(phase_id=phase_id, name=phase_id, order=order)
    for order, phase_id in enumerate(
        [
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
        ],
        start=1,
    )
]
_EXECUTION = "exec-progress"


class _Run:
    """One execution, applied to both read models the way the coordinator would."""

    def __init__(self) -> None:
        self.listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
        self.detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        self.completed = 0

    async def _apply(self, handler: str, payload: dict[str, object]) -> None:
        for projection in (self.listing, self.detail):
            await getattr(projection, handler)(payload)

    async def start(self) -> None:
        await self._apply(
            "on_workflow_execution_started",
            {
                "execution_id": _EXECUTION,
                "workflow_id": "sdlc-implement-v3",
                "workflow_name": "implement-v3",
                "started_at": "2026-10-06T00:00:00+00:00",
                "total_phases": len(_IMPLEMENT_V3),
                "phases": [],
            },
        )

    async def complete(self, phase: PhaseDefinition, verdict: ReviewVerdict | None) -> None:
        """The phase completes and the aggregate decides what runs next."""
        await self._apply(
            "on_phase_completed",
            {"execution_id": _EXECUTION, "phase_id": phase.phase_id, "duration_seconds": 1.0},
        )
        self.completed += 1
        decided = next_phase(_IMPLEMENT_V3, phase.order, verdict)
        if decided is not None:
            event = decided.event(
                workflow_id="sdlc-implement-v3",
                execution_id=_EXECUTION,
                completed_phase_id=phase.phase_id,
            )
            await self._apply("on_next_phase_ready", event.model_dump(mode="json"))

    async def finish(self) -> None:
        await self._apply(
            "on_workflow_completed",
            {
                "execution_id": _EXECUTION,
                "completed_at": datetime(2026, 10, 6, 1, tzinfo=UTC).isoformat(),
                "completed_phases": self.completed,
                "total_phases": len(_IMPLEMENT_V3),
            },
        )

    async def fail(self) -> None:
        await self._apply(
            "on_workflow_failed",
            {
                "execution_id": _EXECUTION,
                "failed_at": datetime(2026, 10, 6, 1, tzinfo=UTC).isoformat(),
                "error_message": "agent crashed",
                "completed_phases": self.completed,
                "total_phases": len(_IMPLEMENT_V3),
            },
        )

    async def progress(self) -> PhaseProgress:
        """Progress as both read models report it; they must agree."""
        summary = await self.listing.get_by_id(_EXECUTION)
        detail = await self.detail.get_by_id(_EXECUTION)
        assert summary is not None
        assert detail is not None
        assert summary.phase_progress == detail.phase_progress
        return summary.phase_progress


def _phase(phase_id: str) -> PhaseDefinition:
    return next(p for p in _IMPLEMENT_V3 if p.phase_id == phase_id)


async def _run_through(run: _Run, steps: list[tuple[str, ReviewVerdict | None]]) -> None:
    await run.start()
    for phase_id, verdict in steps:
        await run.complete(_phase(phase_id), verdict)


_CERTIFIED_AT_ROUND_1: list[tuple[str, ReviewVerdict | None]] = [
    ("premise", None),
    ("implement", None),
    ("verify", ReviewVerdict.BLOCKED),
    ("fix", None),
    ("reverify", ReviewVerdict.CERTIFIED),
]


class TestPhaseProgress:
    async def test_certified_at_round_one_finishes_six_of_six(self) -> None:
        run = _Run()
        await _run_through(run, [*_CERTIFIED_AT_ROUND_1, ("finalize_pr", None)])
        await run.finish()

        progress = await run.progress()

        assert (progress.completed, progress.skipped, progress.possible) == (6, 4, 6)
        assert progress.remaining_possible == 0
        assert progress.percent == 100
        assert progress.display == "6 of 6 (4 phases not needed)"

    async def test_blocked_through_round_three_finishes_ten_of_ten(self) -> None:
        run = _Run()
        steps: list[tuple[str, ReviewVerdict | None]] = [
            ("premise", None),
            ("implement", None),
            ("verify", ReviewVerdict.BLOCKED),
            ("fix", None),
            ("reverify", ReviewVerdict.BLOCKED),
            ("fix_2", None),
            ("reverify_2", ReviewVerdict.BLOCKED),
            ("fix_3", None),
            ("reverify_3", ReviewVerdict.BLOCKED),
            ("finalize_pr", None),
        ]
        await _run_through(run, steps)
        await run.finish()

        progress = await run.progress()

        assert (progress.completed, progress.skipped, progress.possible) == (10, 0, 10)
        assert progress.display == "10 of 10"

    async def test_failed_mid_run_says_how_far_it_got_of_up_to_ten(self) -> None:
        run = _Run()
        await _run_through(run, [("premise", None), ("implement", None), ("verify", None)])
        await run.fail()

        progress = await run.progress()

        assert progress.remaining_possible == 0
        assert progress.percent == 30
        assert progress.display == "3 of up to 10, failed"

    async def test_running_before_any_review_is_phase_three_of_up_to_ten(self) -> None:
        run = _Run()
        await _run_through(run, [("premise", None), ("implement", None)])

        progress = await run.progress()

        assert progress.remaining_possible == 8
        assert progress.display == "phase 3 of up to 10"

    async def test_running_after_certification_drops_the_skipped_rounds(self) -> None:
        run = _Run()
        await _run_through(run, _CERTIFIED_AT_ROUND_1)

        progress = await run.progress()

        assert (progress.skipped, progress.possible, progress.remaining_possible) == (4, 6, 1)
        assert progress.display == "phase 6 of up to 6 (4 phases not needed)"

    async def test_a_decision_applied_twice_counts_its_skips_once(self) -> None:
        run = _Run()
        await _run_through(run, _CERTIFIED_AT_ROUND_1)
        decided = next_phase(_IMPLEMENT_V3, _phase("reverify").order, ReviewVerdict.CERTIFIED)
        assert decided is not None
        again = decided.event(
            workflow_id="sdlc-implement-v3", execution_id=_EXECUTION, completed_phase_id="reverify"
        )
        await run._apply("on_next_phase_ready", again.model_dump(mode="json"))

        assert (await run.progress()).skipped == 4
