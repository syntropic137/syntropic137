"""The scorecard, fed from real events through the projection it reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.scorecard import (
    PhaseType,
    ScorecardProjection,
    TargetStatus,
    compute_scorecard,
    phase_type_of,
)

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)
T0 = NOW - timedelta(hours=10)


def _at(hours: float) -> str:
    return (T0 + timedelta(hours=hours)).isoformat()


async def _run(
    projection: ScorecardProjection,
    execution_id: str,
    *,
    start: float,
    end: float,
    outcome: str,
    classification: str | None = None,
    parent: str | None = None,
    verify_tokens: int = 0,
    model: str = "claude-opus-5-5-20260901",
) -> None:
    await projection.on_execution_requested(
        {"execution_id": execution_id, "workflow_id": "wf", "requested_at": _at(start - 0.5)}
    )
    await projection.on_workflow_execution_started(
        {
            "execution_id": execution_id,
            "workflow_id": "wf",
            "workflow_name": "implement",
            "started_at": _at(start),
            "total_phases": 2,
            "inputs": {},
            "resumed_from": {"parent_execution_id": parent} if parent else None,
        }
    )
    await projection.on_agent_execution_completed(
        {"execution_id": execution_id, "phase_id": "verify", "agent_model": model}
    )
    await projection.on_phase_completed(
        {
            "execution_id": execution_id,
            "phase_id": "verify",
            "session_id": f"s-{execution_id}",
            "success": True,
            "total_tokens": verify_tokens,
            "cache_read_tokens": verify_tokens // 2,
        }
    )
    if outcome == "completed":
        await projection.on_workflow_completed(
            {"execution_id": execution_id, "completed_at": _at(end)}
        )
    elif outcome == "failed":
        await projection.on_workflow_failed(
            {
                "execution_id": execution_id,
                "failed_at": _at(end),
                "failure_classification": classification,
            }
        )
    else:
        await projection.on_execution_cancelled(
            {"execution_id": execution_id, "cancelled_at": _at(end), "phase_id": "verify"}
        )


async def _score(projection: ScorecardProjection, costs: dict[str, Decimal]):
    days = ["2026-10-07"]
    loaded = {r.execution_id: r for r in await projection.runs_for_days(days)}
    for run in list(loaded.values()):
        for member in run.chain:
            if member not in loaded and (got := await projection.get_run(member)):
                loaded[member] = got
    return compute_scorecard(
        runs=loaded,
        cost_by_execution=costs,
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
        classification="platform",
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
        classification="task",
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
    await _run(projection, "a", start=0, end=1, outcome="failed", classification="platform")
    await projection.on_workflow_execution_started(
        {"execution_id": "b", "started_at": _at(2), "resumed_from": {"parent_execution_id": "a"}}
    )

    card = await _score(projection, {})

    assert card.counts.total == 0
    assert card.throughput.peak_concurrency == 1


@pytest.mark.asyncio
async def test_a_failure_recorded_before_classification_is_its_own_bucket() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _run(projection, "a", start=0, end=1, outcome="failed", classification=None)
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
