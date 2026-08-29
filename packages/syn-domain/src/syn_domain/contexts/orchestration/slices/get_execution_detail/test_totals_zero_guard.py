"""A completion event's zero must not erase an accumulated total (#969).

Measured on a live run: the phase reported `duration_seconds: 33.004841` and the
execution reported `total_duration_seconds: 0.0`. Reproduced deterministically
against this projection -- the accumulation was correct until the completion
event overwrote it with a zero.

Tokens survived that same run, so the completion event carries some real totals
and some empty ones. A blind overwrite handles exactly that case worst: it
replaces evidence-backed sums with unset fields.
"""

from __future__ import annotations

import logging

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def projection() -> WorkflowExecutionDetailProjection:
    return WorkflowExecutionDetailProjection(InMemoryProjectionStore())


async def _started(proj: WorkflowExecutionDetailProjection) -> None:
    await proj.on_workflow_execution_started(
        {
            "execution_id": "exec-1",
            "workflow_id": "wf",
            "workflow_name": "wf",
            "phases": [{"phase_id": "p1", "name": "p1"}],
        }
    )


async def _phase_done(proj: WorkflowExecutionDetailProjection) -> None:
    await proj.on_phase_completed(
        {
            "execution_id": "exec-1",
            "phase_id": "p1",
            "input_tokens": 10,
            "output_tokens": 3,
            "duration_seconds": 33.004841,
        }
    )


async def _row(proj: WorkflowExecutionDetailProjection) -> dict:
    return await proj._store.get(proj.PROJECTION_NAME, "exec-1")


class TestZeroDoesNotEraseAccumulatedTotals:
    async def test_the_accumulation_is_correct_before_completion(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        """Precondition. Without this, the guard below could pass vacuously."""
        await _started(projection)
        await _phase_done(projection)
        assert (await _row(projection))["total_duration_seconds"] == 33.004841

    async def test_a_zero_duration_in_the_completion_event_is_ignored(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        """The exact live failure."""
        await _started(projection)
        await _phase_done(projection)
        await projection.on_workflow_completed(
            {"execution_id": "exec-1", "completed_at": "now", "total_duration_seconds": 0.0}
        )
        assert (await _row(projection))["total_duration_seconds"] == 33.004841

    async def test_a_real_total_in_the_completion_event_still_wins(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        """The event stays authoritative when it actually carries a value.

        Without this the fix could degenerate into 'never trust the event',
        which would break restatement after a projection rebuild.
        """
        await _started(projection)
        await _phase_done(projection)
        await projection.on_workflow_completed(
            {"execution_id": "exec-1", "completed_at": "now", "total_duration_seconds": 41.5}
        )
        assert (await _row(projection))["total_duration_seconds"] == 41.5

    async def test_a_zero_is_accepted_when_nothing_was_accumulated(
        self, projection: WorkflowExecutionDetailProjection, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An execution that genuinely did no work must still report zero.

        Asserting the value alone would prove nothing here: startup seeds the
        row at 0.0, so `== 0.0` holds whether completion WROTE the field or
        ignored it entirely -- a codex review caught exactly that. The skip is
        only observable through the warning the guard emits when it fires, so
        that absence is what makes this test falsifiable.
        """
        await _started(projection)
        with caplog.at_level(logging.WARNING):
            await projection.on_workflow_completed(
                {"execution_id": "exec-1", "completed_at": "now", "total_duration_seconds": 0.0}
            )
        assert (await _row(projection))["total_duration_seconds"] == 0.0
        assert not [r for r in caplog.records if "total_duration_seconds" in r.getMessage()], (
            "the guard must not suppress a zero that contradicts nothing"
        )

    async def test_token_totals_stay_authoritative_even_at_zero(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        """The guard is deliberately NARROW.

        A codex review pointed out that `WorkflowCompletedEvent` declares these
        as required final summary values, so 0 is a legitimate authoritative
        answer for tokens -- only the duration case is a known contradiction.
        A blanket truthiness rule would defeat future corrections.
        """
        await _started(projection)
        await _phase_done(projection)
        await projection.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "completed_at": "now",
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_duration_seconds": 0.0,
            }
        )
        row = await _row(projection)
        assert row["total_input_tokens"] == 0, "tokens: the event is authoritative"
        assert row["total_output_tokens"] == 0
        assert row["total_duration_seconds"] == 33.004841, "duration: the zero is suspect"

    async def test_an_empty_artifact_list_CLEARS_an_accumulated_one(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        """Empty can be the correct final state for a list, so it must be applied.

        The artifact must be SEEDED first. A codex review caught that starting
        from `artifact_ids: []` made this pass under the old blanket-truthiness
        guard too -- it asserted nothing about the narrowing.
        """
        await _started(projection)
        await projection.on_phase_completed(
            {
                "execution_id": "exec-1",
                "phase_id": "p1",
                "input_tokens": 10,
                "output_tokens": 3,
                "duration_seconds": 33.004841,
                "artifact_id": "art-1",
            }
        )
        assert (await _row(projection))["artifact_ids"] == ["art-1"], (
            "precondition: an artifact must be accumulated, or this cannot fail"
        )

        await projection.on_workflow_completed(
            {"execution_id": "exec-1", "completed_at": "now", "artifact_ids": []}
        )
        assert (await _row(projection))["artifact_ids"] == []
