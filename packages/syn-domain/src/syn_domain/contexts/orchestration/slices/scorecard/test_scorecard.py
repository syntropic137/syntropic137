"""The scorecard, fed from real events through the projection it reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata, ProjectionResult
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    ResumeOrigin,
)
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionRequestedEvent import (
    ExecutionRequestedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.scorecard import (
    ExecutionSpend,
    PhaseType,
    ScorecardProjection,
    TargetStatus,
    compute_scorecard,
    phase_type_of,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)
T0 = NOW - timedelta(hours=10)


def _at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


async def _deliver(projection: ScorecardProjection, event: DomainEvent) -> None:
    """Through ``handle_event``: the payload the handler gets is the real ``model_dump()``."""
    envelope = EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id="execution",
            aggregate_type="WorkflowExecution",
            aggregate_nonce=1,
            event_type=event.event_type,
            global_nonce=1,
        ),
    )
    result = await projection.handle_event(envelope, MemoryCheckpointStore())
    assert result is ProjectionResult.SUCCESS


def _started(
    execution_id: str, *, start: float, parent: str | None = None
) -> WorkflowExecutionStartedEvent:
    resumed_from = (
        ResumeOrigin(parent_execution_id=parent, inherited_phases=[], resume_phase_id="verify")
        if parent
        else None
    )
    return WorkflowExecutionStartedEvent(
        workflow_id="wf",
        execution_id=execution_id,
        workflow_name="implement",
        started_at=_at(start),
        total_phases=2,
        inputs={},
        resumed_from=resumed_from,
    )


def _failed(
    execution_id: str,
    *,
    end: float,
    classification: FailureClassification,
    phase_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> WorkflowFailedEvent:
    return WorkflowFailedEvent(
        workflow_id="wf",
        execution_id=execution_id,
        failed_at=_at(end),
        failed_phase_id=phase_id,
        error_message="phase failed",
        failure_classification=classification,
        failed_phase_input_tokens=input_tokens,
        failed_phase_output_tokens=output_tokens,
        failed_phase_cache_read_tokens=cache_read_tokens,
        completed_phases=0,
        total_phases=2,
    )


async def _run(
    projection: ScorecardProjection,
    execution_id: str,
    *,
    start: float,
    end: float,
    outcome: str,
    classification: FailureClassification = FailureClassification.UNCLASSIFIED,
    parent: str | None = None,
    verify_tokens: int = 0,
    model: str = "claude-opus-5-5-20260901",
) -> None:
    await _deliver(
        projection,
        ExecutionRequestedEvent(
            execution_id=execution_id, workflow_id="wf", requested_at=_at(start - 0.5)
        ),
    )
    await _deliver(projection, _started(execution_id, start=start, parent=parent))
    await _deliver(
        projection,
        AgentExecutionCompletedEvent(
            workflow_id="wf",
            execution_id=execution_id,
            phase_id="verify",
            session_id=f"s-{execution_id}",
            completed_at=_at(start + 0.1),
            agent_model=model,
        ),
    )
    await _deliver(
        projection,
        PhaseCompletedEvent(
            workflow_id="wf",
            execution_id=execution_id,
            phase_id="verify",
            completed_at=_at(start + 0.1),
            success=True,
            session_id=f"s-{execution_id}",
            total_tokens=verify_tokens,
            cache_read_tokens=verify_tokens // 2,
        ),
    )
    if outcome == "completed":
        await _deliver(
            projection,
            WorkflowCompletedEvent(
                workflow_id="wf",
                execution_id=execution_id,
                completed_at=_at(end),
                total_phases=2,
                completed_phases=2,
                total_input_tokens=0,
                total_output_tokens=0,
                total_tokens=verify_tokens,
                total_duration_seconds=(end - start) * 3600,
                artifact_ids=[],
            ),
        )
    elif outcome == "failed":
        await _deliver(projection, _failed(execution_id, end=end, classification=classification))
    else:
        await _deliver(
            projection,
            ExecutionCancelledEvent(
                workflow_id="wf",
                execution_id=execution_id,
                phase_id="verify",
                cancelled_at=_at(end),
            ),
        )


async def _score(
    projection: ScorecardProjection,
    costs: dict[str, Decimal],
    phase_costs: dict[str, dict[str, Decimal]] | None = None,
):
    days = ["2026-10-07"]
    loaded = {r.execution_id: r for r in await projection.runs_for_days(days)}
    for run in list(loaded.values()):
        for member in run.chain:
            if member not in loaded and (got := await projection.get_run(member)):
                loaded[member] = got
    return compute_scorecard(
        runs=loaded,
        spend_by_execution={
            i: ExecutionSpend(total_usd=c, by_phase=(phase_costs or {}).get(i, {}))
            for i, c in costs.items()
        },
        tool_calls_by_session={"s-a": 10, "s-b": 30},
        now=NOW,
        window_days=1,
    )


@pytest.mark.asyncio
async def test_resumed_chain_counts_once_and_carries_its_failed_runs_cost() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _run(
        projection,
        "a",
        start=0,
        end=1,
        outcome="failed",
        classification=FailureClassification.PLATFORM,
        verify_tokens=8_000_000,
    )
    await _run(
        projection, "b", start=2, end=3, outcome="completed", parent="a", verify_tokens=2_000_000
    )
    await _run(
        projection,
        "c",
        start=2.5,
        end=4,
        outcome="failed",
        classification=FailureClassification.TASK,
        verify_tokens=1_000_000,
        model="gpt-5.4",
    )

    card = await _score(projection, {"a": Decimal("3"), "b": Decimal("2"), "c": Decimal("1")})

    # a and b are one chain: completed, but not platform-failure-free.
    assert card.counts.total == 2
    assert card.counts.completed == 1
    assert card.counts.failed_platform == 0
    assert card.counts.failed_task == 1
    assert card.counts.completed_platform_failure_free == 0
    assert card.counts.platform_failure_free_rate == 0.0
    # Cost includes the failed run the chain resumed from.
    assert card.total_cost_usd == Decimal("6")
    assert card.executions_in_chains == 3
    # Concurrency: b and c overlap from 2.5h to 3h.
    assert card.throughput.peak_concurrency == 2
    assert card.throughput.median_queue_wait_seconds == 1800.0
    # Observed models, not aliases.
    assert [row.key for row in card.by_model] == ["claude-opus-5-5-20260901", "gpt-5.4"]
    verify = next(p for p in card.phases if p.phase_type is PhaseType.VERIFY)
    assert verify.phase_count == 3
    assert verify.median_tokens == 2_000_000
    assert verify.median_tool_calls == 10.0  # nearest rank of [10, 30]
    assert verify.tokens_per_tool_call == 10_000_000 / 40
    targets = {t.name: t.status for t in card.targets}
    assert targets["Median verify tokens"] is TargetStatus.ON_TRACK
    assert targets["Cost per merged PR (USD)"] is TargetStatus.NO_DATA
    assert card.daily[0].counts.total == 2


@pytest.mark.asyncio
async def test_a_superseded_run_is_not_an_outcome_while_its_resume_runs() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _run(
        projection,
        "a",
        start=0,
        end=1,
        outcome="failed",
        classification=FailureClassification.PLATFORM,
    )
    await _deliver(projection, _started("b", start=2, parent="a"))

    card = await _score(projection, {})

    assert card.counts.total == 0
    assert card.throughput.peak_concurrency == 1


@pytest.mark.asyncio
async def test_a_failure_recorded_before_classification_is_its_own_bucket() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _run(projection, "a", start=0, end=1, outcome="failed")
    await _run(projection, "b", start=0, end=1, outcome="cancelled")

    card = await _score(projection, {})

    assert card.counts.failed_unclassified == 1
    assert card.counts.failed_platform == 0
    assert card.counts.cancelled == 1
    assert card.counts.platform_failure_free_rate == 0.0


def test_phase_type_reads_rounds_and_names_the_rest_other() -> None:
    assert phase_type_of("reverify_3") is PhaseType.REVERIFY
    assert phase_type_of("finalize_pr") is PhaseType.FINALIZE
    assert phase_type_of("cross-model-review") is PhaseType.OTHER


@pytest.mark.asyncio
async def test_a_failed_verify_counts_toward_the_verify_tokens_it_spent() -> None:
    """A failing phase emits no PhaseCompleted; its tokens are on WorkflowFailed."""
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _run(projection, "a", start=0, end=1, outcome="completed", verify_tokens=1_000_000)
    await _run(projection, "b", start=1, end=2, outcome="completed", verify_tokens=2_000_000)
    await _deliver(projection, _started("c", start=2))
    failure = _failed(
        "c",
        end=3,
        classification=FailureClassification.TASK,
        phase_id="verify",
        input_tokens=9_000_000,
        output_tokens=500_000,
        cache_read_tokens=7_000_000,
    )
    await _deliver(projection, failure)
    await _deliver(projection, failure)  # redelivered: recorded once

    card = await _score(projection, {})

    verify = next(p for p in card.phases if p.phase_type is PhaseType.VERIFY)
    assert verify.phase_count == 3
    assert verify.median_tokens == 2_000_000
    assert verify.p90_tokens == 16_500_000


@pytest.mark.asyncio
async def test_a_failed_verify_counts_toward_the_verify_cost_it_spent() -> None:
    """Phase cost is read per (execution, phase_id), so the failed verify is costed too.

    Without it the costs are [1, 2]: median 1, p90 2. With it, [1, 2, 9].
    """
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _run(projection, "a", start=0, end=1, outcome="completed", verify_tokens=1_000)
    await _run(projection, "b", start=1, end=2, outcome="completed", verify_tokens=2_000)
    await _deliver(projection, _started("c", start=2))
    await _deliver(
        projection,
        _failed("c", end=3, classification=FailureClassification.TASK, phase_id="verify"),
    )

    card = await _score(
        projection,
        {"a": Decimal("1"), "b": Decimal("2"), "c": Decimal("9")},
        {
            "a": {"verify": Decimal("1")},
            "b": {"verify": Decimal("2")},
            "c": {"verify": Decimal("9")},
        },
    )

    verify = next(p for p in card.phases if p.phase_type is PhaseType.VERIFY)
    assert verify.phases_with_cost == 3
    assert verify.median_cost_usd == Decimal("2")
    assert verify.p90_cost_usd == Decimal("9")
    assert card.daily[-1].median_verify_cost_usd == Decimal("2")
    (workflow,) = card.by_workflow
    assert workflow.phases[0].p90_cost_usd == Decimal("9")


@pytest.mark.asyncio
async def test_a_phase_with_no_recorded_cost_is_not_costed_as_zero() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _run(projection, "a", start=0, end=1, outcome="completed", verify_tokens=1_000)

    card = await _score(projection, {"a": Decimal("1")})

    verify = next(p for p in card.phases if p.phase_type is PhaseType.VERIFY)
    assert verify.phases_with_cost == 0
    assert verify.median_cost_usd is None
