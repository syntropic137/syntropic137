"""Execution cost agrees with session cost when a summary reports no cost (#1420).

A killed phase's summary carries ``total_cost_usd: null`` (#1164). Its session
costs what its turns priced to, on replay and on the session SQL path; the
execution readers roll that session up, so they must give the same total,
model breakdown and phase breakdown - never the summary's own totals re-priced
under its single model.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions import CostCalculator
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.slices.session_cost.test_unreported_cost import (
    _SID,
    _SONNET,
    _TURNS,
    _ZERO_UNRATED_TURN,
    _cost_answer,
    _sql_single,
    _summary_data,
    _summary_row,
)
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostQueryService,
)
from syn_domain.contexts.orchestration.slices.execution_cost.test_projection import (
    MockProjectionStore,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    UnreportedSessionCosts,
    price_grouped_session_summary,
    price_phase_rows,
)

_EID = "exec-1"
_REPORTED_SID = "session-reported"
_REPORTED_COST = Decimal("1.25")

_Cell = int | str | Decimal | list[str] | None


def _execution_row(session_id: str, cost: float | None) -> dict[str, _Cell]:
    """One grouped summary row, as the execution and phase queries project it."""
    row: dict[str, _Cell] = dict(_summary_row(cost))
    row["model"] = row.pop("agent_model")
    row["session_ids"] = [session_id]
    row["total_turns"] = 3
    row["observation_count"] = 1
    return row


async def _replayed(turns: list[tuple[str, int, int]], *, with_reported: bool) -> Decimal:
    projection = ExecutionCostProjection(store=MockProjectionStore())  # type: ignore[arg-type]
    for model, inp, out in turns:
        await projection.on_agent_observation(
            {
                "session_id": _SID,
                "execution_id": _EID,
                "phase_id": "phase-1",
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {"input_tokens": inp, "output_tokens": out, "model": model},
            }
        )
    # A killed run reports its counts as null, not absent.
    killed = {**_summary_data(None), "num_turns": None, "duration_ms": None}
    await projection.on_session_summary(
        {"session_id": _SID, "execution_id": _EID, "phase_id": "phase-1", "data": killed}
    )
    if with_reported:
        await projection.on_session_summary(
            {
                "session_id": _REPORTED_SID,
                "execution_id": _EID,
                "phase_id": "phase-1",
                "data": _summary_data(float(_REPORTED_COST)),
            }
        )
    cost = await projection.get_execution_cost(_EID)
    assert cost is not None
    return cost.total_cost_usd


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("with_reported", [False, True], ids=["unreported-only", "mixed"])
@pytest.mark.parametrize(
    "turns",
    [_TURNS, [*_TURNS, _ZERO_UNRATED_TURN]],
    ids=["priced-multi-model", "with-a-zero-token-unrated-turn"],
)
async def test_execution_readers_roll_up_the_session_answer(
    turns: list[tuple[str, int, int]], with_reported: bool
) -> None:
    session = _sql_single(turns, None)
    total, by_model, unpriced = _cost_answer(session)
    rows = [_execution_row(_SID, None)]
    if with_reported:
        rows.append(_execution_row(_REPORTED_SID, float(_REPORTED_COST)))
        total += _REPORTED_COST
    unreported = UnreportedSessionCosts({_SID: session})

    grouped = price_grouped_session_summary(rows, CostCalculator(), unreported.fork())  # type: ignore[arg-type]
    phases = price_phase_rows(rows, CostCalculator(), unreported.fork())  # type: ignore[arg-type]
    listed = ExecutionCostQueryService(pool=None)._build_from_summary(  # type: ignore[arg-type]
        _EID, rows, tool_counts={}, phase_map={}, unreported=unreported.fork()
    )

    assert grouped.total_cost == total
    assert grouped.unpriced_observation_count == unpriced
    assert listed.total_cost_usd == total
    assert phases.cost_by_phase == {"phase-1": total}
    assert sum(phases.models_by_phase["phase-1"].values()) == total
    # The unreported session's own breakdown, not one bucket for the summary model.
    rolled_up = dict(grouped.cost_by_model)
    if with_reported:
        assert rolled_up.pop(_SONNET) == _REPORTED_COST
    assert rolled_up == by_model
    assert await _replayed(turns, with_reported=with_reported) == total


@pytest.mark.unit
def test_a_session_settles_once_however_many_rows_name_it() -> None:
    session = _sql_single(_TURNS, None)
    rows = [_execution_row(_SID, None), _execution_row(_SID, None)]

    grouped = price_grouped_session_summary(
        rows,  # type: ignore[arg-type]
        CostCalculator(),
        UnreportedSessionCosts({_SID: session}),
    )

    assert grouped.total_cost == session.total_cost_usd
