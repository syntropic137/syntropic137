"""Tests for PhaseResultBuilder."""

from __future__ import annotations

from datetime import UTC, datetime

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.PhaseResultBuilder import (
    PhaseResultBuilder,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)


class TestPhaseResultBuilder:
    def test_success_result(self) -> None:
        tokens = TokenAccumulator()
        tokens.record(100, 200)
        started = datetime.now(UTC)

        result = PhaseResultBuilder.success(
            phase_id="p1",
            started_at=started,
            session_id="s1",
            artifact_ids=["a1", "a2"],
            tokens=tokens,
        )
        assert result.phase_id == "p1"
        assert result.status == PhaseStatus.COMPLETED
        assert result.session_id == "s1"
        assert result.artifact_id == "a1"
        assert result.input_tokens == 100
        assert result.output_tokens == 200
        assert result.total_tokens == 300

    def test_success_no_artifacts(self) -> None:
        tokens = TokenAccumulator()
        result = PhaseResultBuilder.success(
            phase_id="p1",
            started_at=datetime.now(UTC),
            session_id="s1",
            artifact_ids=[],
            tokens=tokens,
        )
        assert result.artifact_id is None

    def test_failure_result(self) -> None:
        started = datetime.now(UTC)
        result = PhaseResultBuilder.failure(
            phase_id="p1",
            started_at=started,
            session_id="s1",
            error_message="boom",
        )
        assert result.phase_id == "p1"
        assert result.status == PhaseStatus.FAILED
        assert result.error_message == "boom"
        assert result.session_id == "s1"
