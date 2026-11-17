"""Unit tests for the failure-streak refusal rule (#1569)."""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.failure_streak import (
    FailureStreak,
    StreakRefusal,
    should_refuse,
)


def streak(length: int) -> FailureStreak:
    return FailureStreak(
        workflow_id="wf-1",
        length=length,
        execution_ids=tuple(f"e{i}" for i in range(1, length + 1)),
    )


@pytest.mark.unit
class TestShouldRefuse:
    def test_below_the_threshold_is_not_refused(self) -> None:
        assert should_refuse(streak(4), threshold=5) is None

    def test_at_the_threshold_is_refused_with_the_streak(self) -> None:
        assert should_refuse(streak(5), threshold=5) == StreakRefusal(
            workflow_id="wf-1",
            length=5,
            threshold=5,
            execution_ids=("e1", "e2", "e3", "e4", "e5"),
        )

    def test_over_the_threshold_is_refused(self) -> None:
        refusal = should_refuse(streak(29), threshold=5)
        assert refusal is not None
        assert refusal.length == 29

    def test_threshold_zero_refuses_nothing(self) -> None:
        assert should_refuse(streak(500), threshold=0) is None

    def test_no_streak_is_never_refused(self) -> None:
        assert should_refuse(FailureStreak(workflow_id="wf-1"), threshold=1) is None

    def test_the_description_names_reason_length_threshold_and_last_executions(self) -> None:
        refusal = should_refuse(streak(7), threshold=3)
        assert refusal is not None

        described = refusal.describe()

        assert described.startswith("failure_streak: ")
        assert "failed 7 times" in described
        assert "threshold of 3" in described
        # The last five, not the first two.
        assert "e3, e4, e5, e6, e7" in described
        assert "e2," not in described
