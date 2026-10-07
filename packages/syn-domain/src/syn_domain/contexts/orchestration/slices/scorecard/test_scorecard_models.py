"""Model rows are what each phase's session REPORTED, never what was configured,
and a model's phase statistics hold only the phases it ran (#1727 B1, B2)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.scorecard import (
    ExecutionSpend,
    PhaseType,
    ScorecardProjection,
    compute_scorecard,
)
from syn_domain.contexts.orchestration.slices.scorecard.test_scorecard import (
    NOW,
    _at,
    _deliver,
    _started,
)

pytestmark = pytest.mark.unit

MODEL_A = "claude-opus-5-5-20260901"
MODEL_B = "gpt-5.4"


async def _phase(
    projection: ScorecardProjection,
    execution_id: str,
    phase_id: str,
    tokens: int,
    *,
    configured: str,
) -> None:
    session = f"s-{execution_id}-{phase_id}"
    await _deliver(
        projection,
        AgentExecutionCompletedEvent(
            workflow_id="wf",
            execution_id=execution_id,
            phase_id=phase_id,
            session_id=session,
            completed_at=_at(1),
            agent_model=configured,
        ),
    )
    await _deliver(
        projection,
        PhaseCompletedEvent(
            workflow_id="wf",
            execution_id=execution_id,
            phase_id=phase_id,
            completed_at=_at(1),
            success=True,
            session_id=session,
            total_tokens=tokens,
        ),
    )


async def _complete(projection: ScorecardProjection, execution_id: str) -> None:
    await _deliver(
        projection,
        WorkflowCompletedEvent(
            workflow_id="wf",
            execution_id=execution_id,
            completed_at=_at(3),
            total_phases=2,
            completed_phases=2,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=0,
            total_duration_seconds=0.0,
            artifact_ids=[],
        ),
    )


async def _card(projection: ScorecardProjection, session_models: dict[str, dict[str, Decimal]]):
    runs = {r.execution_id: r for r in await projection.runs_for_days(["2026-10-07"])}
    for run in list(runs.values()):
        for member in run.chain:
            if member not in runs and (got := await projection.get_run(member)):
                runs[member] = got
    return compute_scorecard(
        runs=runs,
        spend_by_execution={i: ExecutionSpend(total_usd=Decimal(0), by_phase={}) for i in runs},
        tool_calls_by_session={},
        cost_by_session_model=session_models,
        now=NOW,
        window_days=1,
    )


async def test_a_configured_alias_is_never_a_model_row() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _deliver(projection, _started("e1", start=0))
    await _phase(projection, "e1", "implement", 100, configured="opus")
    await _phase(projection, "e1", "verify", 900, configured="gpt-sol")
    await _complete(projection, "e1")

    # Only implement's session reported a model; verify reported none.
    card = await _card(projection, {"s-e1-implement": {MODEL_A: Decimal("1")}})

    assert [row.key for row in card.by_model] == [MODEL_A]
    [row] = card.by_model
    assert [p.phase_type for p in row.phases] == [PhaseType.IMPLEMENT]


async def test_a_model_row_holds_only_the_phases_and_cost_that_model_ran() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _deliver(projection, _started("e1", start=0))
    await _phase(projection, "e1", "implement", 100, configured="opus")
    await _phase(projection, "e1", "verify", 900, configured="opus")
    await _complete(projection, "e1")

    card = await _card(
        projection,
        {
            "s-e1-implement": {MODEL_A: Decimal("1.00")},
            "s-e1-verify": {MODEL_B: Decimal("4.00")},
        },
    )

    rows = {row.key: row for row in card.by_model}
    assert [(p.phase_type, p.median_tokens, p.median_cost_usd) for p in rows[MODEL_A].phases] == [
        (PhaseType.IMPLEMENT, 100, Decimal("1.00"))
    ]
    assert [(p.phase_type, p.median_tokens, p.median_cost_usd) for p in rows[MODEL_B].phases] == [
        (PhaseType.VERIFY, 900, Decimal("4.00"))
    ]
    # One chain, one outcome under each model it used.
    assert rows[MODEL_A].counts.total == rows[MODEL_B].counts.total == 1


async def test_a_resume_on_another_model_keeps_each_runs_phases_under_its_own_model() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    await _deliver(projection, _started("a", start=0))
    await _phase(projection, "a", "verify", 900, configured="opus")
    await _deliver(projection, _started("b", start=2, parent="a"))
    await _phase(projection, "b", "verify", 300, configured="opus")
    await _complete(projection, "b")

    card = await _card(
        projection,
        {"s-a-verify": {MODEL_A: Decimal("3")}, "s-b-verify": {MODEL_B: Decimal("1")}},
    )

    rows = {row.key: row for row in card.by_model}
    assert [(p.phase_count, p.median_tokens) for p in rows[MODEL_A].phases] == [(1, 900)]
    assert [(p.phase_count, p.median_tokens) for p in rows[MODEL_B].phases] == [(1, 300)]


async def test_each_day_keeps_its_own_phase_workflow_and_model_distribution() -> None:
    projection = ScorecardProjection(InMemoryProjectionStore())
    # Day 1 (2026-10-06): implement 100 on A. Day 2 (2026-10-07): verify 900 on B.
    for execution_id, start, phase_id, tokens in (
        ("d1", -20, "implement", 100),
        ("d2", 0, "verify", 900),
    ):
        await _deliver(projection, _started(execution_id, start=start))
        await _phase(projection, execution_id, phase_id, tokens, configured="opus")
        await _deliver(
            projection,
            WorkflowCompletedEvent(
                workflow_id="wf",
                execution_id=execution_id,
                completed_at=_at(start + 1),
                total_phases=1,
                completed_phases=1,
                total_input_tokens=0,
                total_output_tokens=0,
                total_tokens=tokens,
                total_duration_seconds=0.0,
                artifact_ids=[],
            ),
        )
    runs = {r.execution_id: r for r in await projection.runs_for_days(["2026-10-06", "2026-10-07"])}
    card = compute_scorecard(
        runs=runs,
        spend_by_execution={},
        tool_calls_by_session={},
        cost_by_session_model={
            "s-d1-implement": {MODEL_A: Decimal("1")},
            "s-d2-verify": {MODEL_B: Decimal("2")},
        },
        now=NOW,
        window_days=2,
    )

    day1, day2 = card.daily
    assert (day1.day, day2.day) == ("2026-10-06", "2026-10-07")
    assert [(p.phase_type, p.median_tokens) for p in day1.phases] == [(PhaseType.IMPLEMENT, 100)]
    assert [(p.phase_type, p.median_tokens) for p in day2.phases] == [(PhaseType.VERIFY, 900)]
    assert [r.key for r in day1.by_model] == [MODEL_A]
    assert [r.key for r in day2.by_model] == [MODEL_B]
    assert [r.counts.total for r in day1.by_workflow] == [1]
    # The days partition the window: their phase counts sum to the window's.
    assert sum(p.phase_count for d in card.daily for p in d.phases) == sum(
        p.phase_count for p in card.phases
    )
