"""Replay and SQL agree on a session whose summary reports no cost (#1420).

The same events go through all three readers: the replayed
``SessionCostProjection``, the single/batch SQL path (``_cost_for`` over a
fetched page) and the list path (``_build_from_summary``). The summary's token
totals and model both differ from the turns' on purpose: re-pricing the summary
under its one model is exactly the answer that used to differ, so a fixture
where it happened to agree would prove nothing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions import zero_usage_group_by
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
    _LIST_ALL_FROM_TOKEN_USAGE_QUERY,
    SessionCostQueryService,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.test_projection import (
    MockProjectionStore,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    _TOKEN_USAGE_FALLBACK_BATCH_QUERY,
    TimescaleSessionCostQuery,
    _PageRows,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost

_SID = "session-killed"
_OPUS = "claude-opus-4-20250514"
_HAIKU = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-20250514"
#: A real model with no rate, so its turns are unpriced rather than guessed.
_UNPRICED = "gpt-5.6-mini"

#: (model, input, output) for each turn. Two priced models plus an unpriced one.
_TURNS = [(_OPUS, 100_000, 20_000), (_OPUS, 50_000, 10_000), (_HAIKU, 300_000, 40_000)]
_UNPRICED_TURN = (_UNPRICED, 10_000, 1_000)
#: A turn with no tokens on an unrated model: a priced zero on every path (#890).
_ZERO_UNRATED_TURN = (_UNPRICED, 0, 0)

_Cell = int | str | Decimal | None


def _summary_data(cost: float | None) -> dict[str, _Cell]:
    # Totals and model unlike any turn's: re-pricing these as Sonnet is the
    # wrong answer this test exists to refuse.
    return {
        "total_input_tokens": 1_000_000,
        "total_output_tokens": 1_000_000,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "total_cost_usd": cost,
        "num_turns": 3,
        "duration_ms": 1_000,
        "model": _SONNET,
    }


def _summary_row(cost: float | None) -> dict[str, _Cell]:
    data = _summary_data(cost)
    return {
        "session_id": _SID,
        "total_input": data["total_input_tokens"],
        "total_output": data["total_output_tokens"],
        "cache_creation": 0,
        "cache_read": 0,
        "sdk_cost": None if cost is None else Decimal(str(cost)),
        "duration_ms_val": 1_000,
        "agent_model": _SONNET,
        "num_turns": 3,
        "tool_count": 0,
        "workspace_id": None,
        "completed_at": None,
        "execution_id": "exec-1",
        "phase_id": "phase-1",
    }


def _turn_rows(turns: list[tuple[str, int, int]]) -> list[dict[str, _Cell]]:
    """The SQL fallback's shape: one row per (session, model, no tokens?), summed.

    The last key is ``zero_usage_group_by``, which both fallback queries group on.
    """
    grouped: dict[tuple[str, bool], dict[str, _Cell]] = {}
    for model, inp, out in turns:
        row = grouped.setdefault(
            (model, inp + out == 0),
            {
                "session_id": _SID,
                "agent_model": model,
                "total_input": 0,
                "total_output": 0,
                "cache_creation": 0,
                "cache_read": 0,
                "started_at": None,
                "last_observation": None,
                "workspace_id": None,
                "observation_count": 0,
                "execution_id": "exec-1",
                "phase_id": "phase-1",
            },
        )
        row["total_input"] = int(row["total_input"] or 0) + inp
        row["total_output"] = int(row["total_output"] or 0) + out
        row["observation_count"] = int(row["observation_count"] or 0) + 1
    return list(grouped.values())


async def _replayed(
    turns: list[tuple[str, int, int]], cost: float | None, *earlier_costs: float | None
) -> SessionCost:
    """Replay the turns, then a summary per ``earlier_costs``, then the newest at ``cost``."""
    store = MockProjectionStore()
    projection = SessionCostProjection(store)  # type: ignore[arg-type]
    for model, inp, out in turns:
        await projection.on_agent_observation(
            {
                "session_id": _SID,
                "event_type": ObservationType.TOKEN_USAGE.value,
                "data": {"input_tokens": inp, "output_tokens": out, "model": model},
            }
        )
    for summary_cost in (*earlier_costs, cost):
        await projection.on_session_summary(
            {"session_id": _SID, "data": _summary_data(summary_cost)}
        )
    cost_doc = await projection.get_session_cost(_SID)
    assert cost_doc is not None
    return cost_doc


def _sql_single(turns: list[tuple[str, int, int]], cost: float | None) -> SessionCost:
    page = _PageRows(
        summaries={_SID: _summary_row(cost)},  # type: ignore[dict-item]
        fallback={_SID: _turn_rows(turns)} if turns else {},  # type: ignore[dict-item]
        tool_counts={},
        started={},
    )
    result = TimescaleSessionCostQuery(pool=None)._cost_for(_SID, page)  # type: ignore[arg-type]
    assert result is not None
    return result


def _sql_list(turns: list[tuple[str, int, int]], cost: float | None) -> SessionCost:
    service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]
    return service._build_from_summary(
        _summary_row(cost), tool_counts={}, started_map={}, turn_rows=_turn_rows(turns)
    )


def _cost_answer(sc: SessionCost) -> tuple[Decimal, dict[str, Decimal], int]:
    return sc.total_cost_usd, dict(sc.cost_by_model), sc.unpriced_observation_count


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(
    "turns",
    [
        _TURNS,
        [*_TURNS, _UNPRICED_TURN],
        [_UNPRICED_TURN],
        [],
        [_ZERO_UNRATED_TURN],
        [*_TURNS, _ZERO_UNRATED_TURN],
        [_ZERO_UNRATED_TURN, _UNPRICED_TURN],
    ],
    ids=[
        "priced-multi-model",
        "with-an-unpriced-turn",
        "only-unpriced",
        "no-turns",
        "zero-token-unrated",
        "zero-token-unrated-beside-priced",
        "zero-and-positive-on-one-unrated-model",
    ],
)
async def test_replay_and_both_sql_paths_give_one_answer(
    turns: list[tuple[str, int, int]],
) -> None:
    replayed = await _replayed(turns, None)

    assert _cost_answer(_sql_single(turns, None)) == _cost_answer(replayed)
    assert _cost_answer(_sql_list(turns, None)) == _cost_answer(replayed)


@pytest.mark.unit
@pytest.mark.anyio
async def test_the_answer_is_the_turns_not_the_summary_repriced() -> None:
    """Agreement alone would also hold if every path re-priced the summary."""
    replayed = await _replayed(_TURNS, None)

    total, by_model, unpriced = _cost_answer(_sql_single(_TURNS, None))

    assert set(by_model) == {_OPUS, _HAIKU}
    assert total == sum(by_model.values())
    assert total != Decimal("18.00")  # 1M + 1M tokens priced as Sonnet
    assert unpriced == 0
    assert total == replayed.total_cost_usd
    # Tokens still come from the summary: its cumulative count is the one to trust.
    assert replayed.input_tokens == 1_000_000


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_summary_with_tokens_and_no_turns_is_unpriced_not_free() -> None:
    """#1164: nothing priced it, so the zero arrives labelled (#890)."""
    replayed = await _replayed([], None)

    assert _cost_answer(replayed) == (Decimal("0"), {}, 1)


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_reported_cost_still_wins_on_every_path() -> None:
    replayed = await _replayed(_TURNS, 1.25)
    single = _sql_single(_TURNS, 1.25)
    listed = _sql_list(_TURNS, 1.25)

    for sc in (replayed, single, listed):
        assert sc.total_cost_usd == Decimal("1.25")
        assert list(sc.cost_by_model.values()) == [Decimal("1.25")]


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(
    "turns",
    [_TURNS, [*_TURNS, _UNPRICED_TURN], []],
    ids=["priced-multi-model", "with-an-unpriced-turn", "no-turns"],
)
async def test_a_null_summary_after_a_reported_one_costs_the_turns(
    turns: list[tuple[str, int, int]],
) -> None:
    """The newest summary wins, and SQL reads only it: the earlier $1.25 is gone."""
    replayed = await _replayed(turns, None, 1.25)

    assert _cost_answer(replayed) == _cost_answer(await _replayed(turns, None))
    assert _cost_answer(_sql_single(turns, None)) == _cost_answer(replayed)
    assert _cost_answer(_sql_list(turns, None)) == _cost_answer(replayed)
    assert replayed.total_cost_usd != Decimal("1.25")


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_reported_summary_after_a_null_one_still_wins() -> None:
    replayed = await _replayed(_TURNS, 1.25, None)

    assert _cost_answer(replayed) == _cost_answer(_sql_single(_TURNS, 1.25))
    assert replayed.total_cost_usd == Decimal("1.25")


@pytest.mark.unit
@pytest.mark.anyio
async def test_zero_and_positive_turns_on_one_unrated_model_price_apart() -> None:
    """Replay prices the empty turn as a zero; summed with the other it would go unpriced."""
    turns = [_ZERO_UNRATED_TURN, _UNPRICED_TURN]
    expected = (Decimal("0"), {_UNPRICED: Decimal("0")}, 1)

    assert _cost_answer(await _replayed(turns, None)) == expected
    assert _cost_answer(_sql_single(turns, None)) == expected
    assert _cost_answer(_sql_list(turns, None)) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "query",
    [_TOKEN_USAGE_FALLBACK_BATCH_QUERY, _LIST_ALL_FROM_TOKEN_USAGE_QUERY],
    ids=["single-and-batch", "list"],
)
def test_both_turn_queries_group_empty_turns_apart(query: str) -> None:
    """``_turn_rows`` models this grouping; the queries must actually do it."""
    group_by = query.split("GROUP BY", 1)[1]

    assert zero_usage_group_by() in group_by
