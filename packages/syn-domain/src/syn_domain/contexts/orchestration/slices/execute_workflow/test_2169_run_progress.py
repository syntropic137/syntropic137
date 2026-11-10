"""A run picked up from its stream keeps every earlier phase's totals (#2169)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionMetrics,
)
from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
    ArtifactsCollectedForPhaseEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.run_progress import RunProgress

pytestmark = pytest.mark.unit

_AT = datetime(2026, 11, 10, tzinfo=UTC)


def _collected(phase_id: str, *ids: str) -> ArtifactsCollectedForPhaseEvent:
    return ArtifactsCollectedForPhaseEvent(
        workflow_id="wf",
        execution_id="exec",
        phase_id=phase_id,
        artifact_ids=list(ids),
        collected_at=_AT,
    )


def _completed(phase_id: str, tokens: int) -> PhaseCompletedEvent:
    return PhaseCompletedEvent(
        workflow_id="wf",
        execution_id="exec",
        phase_id=phase_id,
        completed_at=_AT,
        success=True,
        input_tokens=tokens,
        total_tokens=tokens,
    )


def test_two_phases_completed_before_the_restart_are_both_totalled() -> None:
    progress = RunProgress.from_stream(
        None,
        [
            _collected("plan", "a-plan"),
            _completed("plan", 100),
            _collected("build", "a-build", "a-report"),
            _completed("build", 0),
        ],
    )

    assert progress.completed_phase_ids == ["plan", "build"]
    assert progress.artifact_ids == ["a-plan", "a-build", "a-report"]
    metrics = ExecutionMetrics.from_results(progress.phase_results)
    assert (metrics.completed_phases, metrics.total_input_tokens) == (2, 100)


def test_a_stream_with_no_completed_phase_starts_empty() -> None:
    assert RunProgress.from_stream(None, [_collected("plan")]) == RunProgress()
