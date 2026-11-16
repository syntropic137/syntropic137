"""Unit tests for FailureStreakProjection (#1569).

Every event goes in through ``handle_event`` as the real event class, the way
the coordinator delivers it, so these tests cover the dispatch and the
payload shape as well as the rules.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.failure_streak import (
    FailureStreak,
    FailureStreakProjection,
)
from syn_domain.contexts.orchestration.slices.failure_streak.streak import (
    RECENT_EXECUTIONS_KEPT,
)

T0 = datetime(2026, 11, 1, tzinfo=UTC)
_nonce = count(1)


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def failed(
    execution_id: str,
    *,
    workflow_id: str = "wf-1",
    minute: int = 0,
    classification: FailureClassification = FailureClassification.PLATFORM,
) -> WorkflowFailedEvent:
    return WorkflowFailedEvent(
        workflow_id=workflow_id,
        execution_id=execution_id,
        failed_at=_at(minute),
        error_message="boom",
        failure_classification=classification,
        completed_phases=0,
        total_phases=1,
    )


def completed(execution_id: str, *, workflow_id: str = "wf-1") -> WorkflowCompletedEvent:
    return WorkflowCompletedEvent(
        workflow_id=workflow_id,
        execution_id=execution_id,
        completed_at=T0,
        total_phases=1,
        completed_phases=1,
        total_input_tokens=0,
        total_output_tokens=0,
        total_tokens=0,
        total_duration_seconds=1.0,
        artifact_ids=[],
    )


def cancelled(execution_id: str, *, workflow_id: str = "wf-1") -> ExecutionCancelledEvent:
    return ExecutionCancelledEvent(
        workflow_id=workflow_id,
        execution_id=execution_id,
        phase_id="p-1",
        cancelled_at=T0,
    )


async def feed(projection: FailureStreakProjection, *events: DomainEvent) -> None:
    checkpoints = MemoryCheckpointStore()
    for event in events:
        nonce = next(_nonce)
        await projection.handle_event(
            EventEnvelope(
                event=event,
                metadata=EventMetadata(
                    aggregate_id=getattr(event, "execution_id", "exec"),
                    aggregate_type="WorkflowExecution",
                    aggregate_nonce=nonce,
                    event_type=event.event_type,
                    global_nonce=nonce,
                ),
            ),
            checkpoints,
        )


@pytest.fixture
def projection() -> FailureStreakProjection:
    return FailureStreakProjection(InMemoryProjectionStore())


@pytest.mark.unit
class TestFailureStreak:
    async def test_platform_failures_count_up(self, projection: FailureStreakProjection) -> None:
        await feed(
            projection, failed("e1", minute=1), failed("e2", minute=2), failed("e3", minute=3)
        )

        streak = await projection.get_streak("wf-1")
        assert streak.length == 3
        assert streak.execution_ids == ("e1", "e2", "e3")
        assert streak.first_failed_at == _at(1)
        assert streak.last_failed_at == _at(3)

    async def test_unclassified_failures_extend_the_streak(
        self, projection: FailureStreakProjection
    ) -> None:
        await feed(
            projection,
            failed("e1", classification=FailureClassification.UNCLASSIFIED),
            failed("e2", classification=FailureClassification.PLATFORM),
        )

        assert (await projection.get_streak("wf-1")).length == 2

    async def test_a_completion_resets_the_streak(
        self, projection: FailureStreakProjection
    ) -> None:
        await feed(projection, failed("e1"), failed("e2"), completed("e3"), failed("e4", minute=9))

        streak = await projection.get_streak("wf-1")
        assert streak.length == 1
        assert streak.execution_ids == ("e4",)
        assert streak.first_failed_at == _at(9)

    @pytest.mark.parametrize(
        "classification",
        [
            FailureClassification.TASK,
            FailureClassification.CORRECT_REFUSAL,
            FailureClassification.GATE,
        ],
    )
    async def test_a_non_platform_failure_neither_extends_nor_resets(
        self, projection: FailureStreakProjection, classification: FailureClassification
    ) -> None:
        await feed(
            projection, failed("e1"), failed("e2", classification=classification), failed("e3")
        )

        streak = await projection.get_streak("wf-1")
        assert streak.length == 2
        assert streak.execution_ids == ("e1", "e3")

    async def test_a_cancel_neither_extends_nor_resets(
        self, projection: FailureStreakProjection
    ) -> None:
        await feed(projection, failed("e1"), cancelled("e2"), failed("e3"))

        assert (await projection.get_streak("wf-1")).length == 2

    async def test_templates_are_independent(self, projection: FailureStreakProjection) -> None:
        await feed(
            projection,
            failed("a1", workflow_id="wf-a"),
            failed("b1", workflow_id="wf-b"),
            failed("a2", workflow_id="wf-a"),
            completed("b2", workflow_id="wf-b"),
        )

        assert (await projection.get_streak("wf-a")).length == 2
        assert (await projection.get_streak("wf-b")).length == 0

    async def test_the_same_failure_twice_counts_once(
        self, projection: FailureStreakProjection
    ) -> None:
        event = failed("e1")
        await feed(projection, event, event)

        assert (await projection.get_streak("wf-1")).length == 1

    async def test_a_replay_from_scratch_gives_the_same_streaks(
        self, projection: FailureStreakProjection
    ) -> None:
        history = (
            failed("a1", workflow_id="wf-a", minute=1),
            completed("a2", workflow_id="wf-a"),
            failed("a3", workflow_id="wf-a", minute=3),
            failed("b1", workflow_id="wf-b", minute=4),
            failed("a4", workflow_id="wf-a", minute=5),
        )
        await feed(projection, *history)
        before = await projection.list_streaks(min_length=0)

        await projection.clear_all_data()
        await feed(projection, *history)

        assert await projection.list_streaks(min_length=0) == before
        assert [streak.length for streak in before] == [2, 1]

    async def test_the_count_stays_exact_past_the_kept_ids(
        self, projection: FailureStreakProjection
    ) -> None:
        total = RECENT_EXECUTIONS_KEPT + 5
        await feed(projection, *(failed(f"e{i}", minute=i) for i in range(total)))

        streak = await projection.get_streak("wf-1")
        assert streak.length == total
        assert len(streak.execution_ids) == RECENT_EXECUTIONS_KEPT
        assert streak.execution_ids[-1] == f"e{total - 1}"
        assert streak.first_failed_at == _at(0)

    async def test_list_streaks_filters_by_length_longest_first(
        self, projection: FailureStreakProjection
    ) -> None:
        await feed(
            projection,
            failed("a1", workflow_id="wf-a"),
            failed("b1", workflow_id="wf-b"),
            failed("b2", workflow_id="wf-b"),
            failed("c1", workflow_id="wf-c"),
            completed("c2", workflow_id="wf-c"),
        )

        assert [s.workflow_id for s in await projection.list_streaks(min_length=1)] == [
            "wf-b",
            "wf-a",
        ]
        assert [s.workflow_id for s in await projection.list_streaks(min_length=2)] == ["wf-b"]

    async def test_an_unseen_template_has_no_streak(
        self, projection: FailureStreakProjection
    ) -> None:
        assert await projection.get_streak("wf-never") == FailureStreak(workflow_id="wf-never")
