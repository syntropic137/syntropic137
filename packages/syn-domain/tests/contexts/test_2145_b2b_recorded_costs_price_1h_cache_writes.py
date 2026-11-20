"""#2145 B2b: recorded execution and session costs price 1-hour cache writes at the 1-hour rate.

A ``TOKEN_USAGE`` row stores every cache write in ``cache_creation_tokens`` and
the 1-hour share beside it in ``cache_creation_1h_tokens`` (B2a, #2331). These
tests drive that row through the things that READ it - the two cost
projections and the Timescale grouped queries - and check the dollars that
come out, not the split helper in isolation.

Opus 5.5 writes the cache at $5.00/MTok for 5 minutes and $8.00/MTok for 1 hour.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from event_sourcing import MemoryCheckpointStore, ProjectionCheckpoint, SubscriptionCoordinator

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_adapters.subscriptions.projection_adapters import (
    ExecutionCostAdapter,
    SessionCostAdapter,
)
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost import (
    query_service as session_query_service,
)
from syn_domain.contexts.agent_sessions.slices.session_cost import (
    timescale_query as session_timescale,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.orchestration.slices.execution_cost import (
    query_service as execution_query_service,
)
from syn_domain.contexts.orchestration.slices.execution_cost import (
    timescale_query as execution_timescale,
)
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)
from syn_shared.agents import ModelId

if TYPE_CHECKING:
    from collections.abc import Mapping

    import asyncpg

pytestmark = pytest.mark.unit

_OPUS = ModelId.CLAUDE_OPUS_5_5.value
_MILLION = 1_000_000

#: One row, every cache write 1-hour: $8.00, where pricing it all at 5 minutes said $5.00.
_ALL_1H = {"cache_creation_tokens": _MILLION, "cache_creation_1h_tokens": _MILLION}
#: A row written before B2a: no 1-hour key at all.
_LEGACY = {"cache_creation_tokens": _MILLION}
#: 600k 1-hour + 400k 5-minute: 0.6 * 8.00 + 0.4 * 5.00 = 6.80.
_MIXED = {"cache_creation_tokens": _MILLION, "cache_creation_1h_tokens": 600_000}

_CASES = [
    pytest.param(_ALL_1H, Decimal("8.00"), _MILLION, id="all-1h"),
    pytest.param(_LEGACY, Decimal("5.00"), 0, id="legacy-row"),
    pytest.param(_MIXED, Decimal("6.80"), 600_000, id="mixed"),
]


def _token_usage(cache: Mapping[str, int]) -> dict[str, str | dict[str, str | int]]:
    return {
        "session_id": "session-1",
        "execution_id": "exec-1",
        "observation_type": ObservationType.TOKEN_USAGE.value,
        "event_type": ObservationType.TOKEN_USAGE.value,
        "data": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "model": _OPUS,
            **cache,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("cache", "expected", "one_hour"), _CASES)
async def test_execution_cost_projection_prices_recorded_1h_writes(
    cache: Mapping[str, int], expected: Decimal, one_hour: int
) -> None:
    projection = ExecutionCostProjection(InMemoryProjectionStore())

    await projection.on_agent_observation(_token_usage(cache))

    cost = await projection.get_execution_cost("exec-1")
    assert cost is not None
    assert cost.total_cost_usd == expected
    assert cost.cost_by_model[_OPUS] == expected
    assert cost.cache_creation_tokens == _MILLION
    assert cost.cache_creation_1h_tokens == one_hour


@pytest.mark.asyncio
@pytest.mark.parametrize(("cache", "expected", "one_hour"), _CASES)
async def test_session_cost_projection_prices_recorded_1h_writes(
    cache: Mapping[str, int], expected: Decimal, one_hour: int
) -> None:
    projection = SessionCostProjection(InMemoryProjectionStore())

    await projection.on_agent_observation(_token_usage(cache))

    cost = await projection.get_session_cost("session-1")
    assert cost is not None
    assert cost.total_cost_usd == expected
    assert cost.cache_creation_tokens == _MILLION
    assert cost.cache_creation_1h_tokens == one_hour


@pytest.mark.asyncio
async def test_legacy_row_prices_exactly_as_the_5_minute_total() -> None:
    """A row with no 1-hour key costs exactly what pricing the total at 5 minutes did."""
    before = CostCalculator().resolve_pricing(_OPUS)
    assert before is not None
    expected = before.calculate_cost(0, 0, _MILLION, 0)

    execution = ExecutionCostProjection(InMemoryProjectionStore())
    session = SessionCostProjection(InMemoryProjectionStore())
    await execution.on_agent_observation(_token_usage(_LEGACY))
    await session.on_agent_observation(_token_usage(_LEGACY))

    execution_cost = await execution.get_execution_cost("exec-1")
    session_cost = await session.get_session_cost("session-1")
    assert execution_cost is not None
    assert session_cost is not None
    assert execution_cost.total_cost_usd == expected
    assert session_cost.total_cost_usd == expected
    assert execution_cost.cache_creation_1h_tokens == 0
    assert session_cost.cache_creation_1h_tokens == 0


@pytest.mark.asyncio
async def test_cache_creation_1h_tokens_sums_across_turns_and_survives_the_store() -> None:
    """The counter is summed per turn and read back from the stored dict, not just held in memory."""
    store = InMemoryProjectionStore()
    projection = ExecutionCostProjection(store)

    await projection.on_agent_observation(_token_usage(_MIXED))
    await projection.on_agent_observation(_token_usage(_ALL_1H))

    cost = await ExecutionCostProjection(store).get_execution_cost("exec-1")
    assert cost is not None
    assert cost.cache_creation_1h_tokens == 1_600_000
    assert cost.total_cost_usd == Decimal("14.80")


# --- Timescale read paths ---------------------------------------------------


#: A column value the grouped token_usage SQL can return.
_Cell = int | str | list[str] | Decimal | None


class _FakeRow:
    """An asyncpg Record as the grouped token_usage SQL returns one."""

    def __init__(self, data: Mapping[str, _Cell]) -> None:
        self._data = dict(data)

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _grouped_row(
    cache_creation: int, cache_creation_1h: int | None, *, session_id: str = "session-1"
) -> asyncpg.Record:
    row: dict[str, _Cell] = {
        "model": _OPUS,
        "agent_model": _OPUS,
        "total_input": 0,
        "total_output": 0,
        "cache_creation": cache_creation,
        "cache_read": 0,
        "session_ids": [session_id],
        "session_id": session_id,
        "observation_count": 1,
        "started_at": None,
        "last_observation": None,
        "workspace_id": None,
        "execution_id": "exec-1",
        "phase_id": None,
    }
    if cache_creation_1h is not None:
        row["cache_creation_1h"] = cache_creation_1h
    return _FakeRow(row)  # type: ignore[return-value]


_GROUPED_CASES = [
    pytest.param(_MILLION, _MILLION, Decimal("8.00"), id="all-1h"),
    pytest.param(_MILLION, None, Decimal("5.00"), id="legacy-no-column"),
    pytest.param(_MILLION, 600_000, Decimal("6.80"), id="mixed"),
]


@pytest.mark.parametrize(("total", "one_hour", "expected"), _GROUPED_CASES)
def test_execution_grouped_token_usage_prices_the_summed_1h_share(
    total: int, one_hour: int | None, expected: Decimal
) -> None:
    grouped = execution_timescale.price_grouped_token_usage(
        [_grouped_row(total, one_hour)], CostCalculator()
    )

    assert grouped.total_cost == expected
    assert grouped.cache_creation_1h == (one_hour or 0)


@pytest.mark.parametrize(("total", "one_hour", "expected"), _GROUPED_CASES)
def test_session_grouped_rows_price_the_summed_1h_share(
    total: int, one_hour: int | None, expected: Decimal
) -> None:
    totals = session_timescale.price_session_rows(
        [_grouped_row(total, one_hour)], CostCalculator(), "session-1"
    )

    assert totals is not None
    assert totals.total_cost == expected
    assert totals.cache_creation_1h == (one_hour or 0)
    # The token-type split prices the same row the same way, so it still sums to the total.
    assert totals.cost_by_token_type is not None
    assert totals.cost_by_token_type.cache_creation_usd == expected


_SUMS_1H = "SUM(COALESCE((data->>'cache_creation_1h_tokens')::int, 0)) as cache_creation_1h"


@pytest.mark.parametrize(
    "sql",
    [
        pytest.param(execution_timescale._TOKEN_USAGE_FALLBACK_QUERY, id="execution-fallback"),
        pytest.param(
            execution_query_service._LIST_ALL_FROM_TOKEN_USAGE_QUERY, id="execution-list-all"
        ),
        pytest.param(execution_query_service._BY_IDS_FROM_TOKEN_USAGE_QUERY, id="execution-by-ids"),
        pytest.param(session_timescale._TOKEN_USAGE_FALLBACK_BATCH_QUERY, id="session-fallback"),
        pytest.param(session_query_service._LIST_ALL_FROM_TOKEN_USAGE_QUERY, id="session-list-all"),
    ],
)
def test_grouped_token_usage_sql_sums_the_1h_share(sql: str) -> None:
    """Every grouped token_usage query hands its pricer the 1-hour share, 0 for legacy rows."""
    assert _SUMS_1H in sql


def test_cost_projection_versions_are_bumped_for_the_1h_reprice() -> None:
    """The stored cost read models change shape and value, so both must replay (#2145 B2b)."""
    assert ExecutionCostAdapter.VERSION >= 2
    assert SessionCostAdapter.VERSION >= 2


_UNRELATED = "tool_timeline"


@pytest.mark.asyncio
@pytest.mark.parametrize(("cache", "expected", "one_hour"), _CASES)
@pytest.mark.parametrize("cost", ["execution", "session"])
async def test_version_rebuild_clears_old_totals_before_replaying(
    cost: str, cache: Mapping[str, int], expected: Decimal, one_hour: int
) -> None:
    """A v1 -> v2 mismatch through the real coordinator replays onto an empty read model.

    The cost documents are running sums: without the clear, replaying the same
    observation onto the v1 total counts it twice ($13 for an all-1h turn).
    """
    store = InMemoryProjectionStore()
    projection: ExecutionCostProjection | SessionCostProjection
    if cost == "execution":
        projection = ExecutionCostProjection(store)
        adapter: ExecutionCostAdapter | SessionCostAdapter = ExecutionCostAdapter(projection)
    else:
        projection = SessionCostProjection(store)
        adapter = SessionCostAdapter(projection)

    async def read() -> tuple[int, int, Decimal]:
        if isinstance(projection, ExecutionCostProjection):
            stored = await projection.get_execution_cost("exec-1")
        else:
            stored = await projection.get_session_cost("session-1")
        assert stored is not None
        return stored.cache_creation_tokens, stored.cache_creation_1h_tokens, stored.total_cost_usd

    # What v1 stored for this turn: every write at 5 minutes. Plus another
    # projection's namespace in the same store, which the clear must not touch.
    await projection.on_agent_observation(_token_usage(_LEGACY))
    await store.save(_UNRELATED, "kept", {"value": 1})
    checkpoints = MemoryCheckpointStore()
    await checkpoints.save_checkpoint(
        ProjectionCheckpoint(
            projection_name=adapter.get_name(),
            global_position=10,
            updated_at=datetime.now(UTC),
            version=1,
        )
    )
    coordinator = SubscriptionCoordinator(
        event_store=Mock(), checkpoint_store=checkpoints, projections=[adapter]
    )

    assert await coordinator._resume_position(adapter.get_name(), adapter) == 0
    assert await checkpoints.get_checkpoint(adapter.get_name()) is None
    assert await store.get_all(projection.PROJECTION_NAME) == []
    assert await store.get(_UNRELATED, "kept") == {"value": 1}

    # Replay the same observation, now read with its 1-hour split.
    await projection.on_agent_observation(_token_usage(cache))
    assert await read() == (_MILLION, one_hour, expected)

    # A second restart at the new version resumes after the checkpoint and clears nothing.
    await checkpoints.save_checkpoint(
        ProjectionCheckpoint(
            projection_name=adapter.get_name(),
            global_position=10,
            updated_at=datetime.now(UTC),
            version=adapter.get_version(),
        )
    )
    assert await coordinator._resume_position(adapter.get_name(), adapter) == 11
    assert await read() == (_MILLION, one_hour, expected)


# --- A summary arrives: the 1-hour count must not fall back to zero ----------
#
# A session_summary row records every cache write in one total and no TTL
# split. Every reader that switches to it on completion takes the split from
# the same sessions' token_usage rows.

_COMPLETION_CASES = [
    pytest.param(_MILLION, Decimal("8.00"), id="all-1h"),
    pytest.param(None, Decimal("5.00"), id="legacy-row"),
    pytest.param(600_000, Decimal("6.80"), id="mixed"),
]
_REPORTED = [pytest.param(True, id="reported-cost"), pytest.param(False, id="unreported-cost")]


def _summary_row(sdk_cost: Decimal | None, total_input: int = 0) -> asyncpg.Record:
    """One completed session's ``session_summary`` row: a total and no TTL split."""
    return _FakeRow(  # type: ignore[return-value]
        {
            "session_id": "session-1",
            "model": _OPUS,
            "agent_model": _OPUS,
            "total_input": total_input,
            "total_output": 0,
            "cache_creation": _MILLION,
            "cache_read": 0,
            "sdk_cost": sdk_cost,
            "num_turns": 1,
            "total_turns": 1,
            "duration_ms_val": 0,
            "completed_at": None,
            "workspace_id": None,
            "execution_id": "exec-1",
            "phase_id": None,
            "session_ids": ["session-1"],
            "observation_count": 1,
        }
    )


def _session_page(
    summary: asyncpg.Record | None, turns: list[asyncpg.Record]
) -> session_timescale._PageRows:
    summaries = {"session-1": summary} if summary is not None else {}
    return session_timescale._PageRows(summaries, {"session-1": turns}, {}, {})


@pytest.mark.parametrize("reported", _REPORTED)
@pytest.mark.parametrize(("one_hour", "expected"), _COMPLETION_CASES)
def test_session_detail_keeps_the_1h_count_after_its_summary_arrives(
    one_hour: int | None, expected: Decimal, reported: bool
) -> None:
    query = session_timescale.TimescaleSessionCostQuery(Mock())
    turns = [_grouped_row(_MILLION, one_hour)]
    summary = _summary_row(expected if reported else None)

    before = query._cost_for("session-1", _session_page(None, turns))
    after = query._cost_for("session-1", _session_page(summary, turns))

    assert before is not None
    assert after is not None
    assert before.cache_creation_1h_tokens == (one_hour or 0)
    assert after.cache_creation_1h_tokens == before.cache_creation_1h_tokens
    assert after.total_cost_usd == before.total_cost_usd == expected
    assert after.is_finalized


@pytest.mark.parametrize("reported", _REPORTED)
def test_session_cache_write_dollars_survive_an_authoritative_summary(reported: bool) -> None:
    """1M input ($4) + 1M 1-hour writes ($8): the split stays $8 of $12 after completion."""
    query = session_timescale.TimescaleSessionCostQuery(Mock())
    turn = _FakeRow({**_grouped_row(_MILLION, _MILLION)._data, "total_input": _MILLION})  # type: ignore[attr-defined]
    turns: list[asyncpg.Record] = [turn]  # type: ignore[list-item]
    summary = _summary_row(Decimal("12.00") if reported else None, total_input=_MILLION)

    before = query._cost_for("session-1", _session_page(None, turns))
    after = query._cost_for("session-1", _session_page(summary, turns))

    assert before is not None
    assert after is not None
    assert before.cost_by_token_type is not None
    assert after.cost_by_token_type is not None
    assert after.total_cost_usd == before.total_cost_usd == Decimal("12.00")
    assert before.cost_by_token_type.cache_creation_usd == Decimal("8.00")
    assert after.cost_by_token_type.cache_creation_usd == Decimal("8.00")


@pytest.mark.parametrize("reported", _REPORTED)
@pytest.mark.parametrize(("one_hour", "expected"), _COMPLETION_CASES)
def test_session_list_keeps_the_1h_count_after_its_summary_arrives(
    one_hour: int | None, expected: Decimal, reported: bool
) -> None:
    query = session_query_service.SessionCostQueryService(Mock())
    turns = [_grouped_row(_MILLION, one_hour)]

    before = query._build_from_token_usage("session-1", turns, {}, {})
    after = query._build_from_summary(_summary_row(expected if reported else None), {}, {}, turns)

    assert before is not None
    assert before.cache_creation_1h_tokens == (one_hour or 0)
    assert after.cache_creation_1h_tokens == before.cache_creation_1h_tokens
    assert after.total_cost_usd == before.total_cost_usd == expected


def _unreported(
    expected: Decimal, one_hour: int | None, reported: bool
) -> execution_timescale.UnreportedSessionCosts:
    """What the session reader answers for a session whose summary reports no cost."""
    if reported:
        return execution_timescale.UnreportedSessionCosts()
    session = SessionCost(
        session_id="session-1",
        cache_creation_tokens=_MILLION,
        cache_creation_1h_tokens=one_hour or 0,
        total_cost_usd=expected,
        cost_by_model={_OPUS: expected},
    )
    return execution_timescale.UnreportedSessionCosts({"session-1": session})


@pytest.mark.parametrize("reported", _REPORTED)
@pytest.mark.parametrize(("one_hour", "expected"), _COMPLETION_CASES)
def test_execution_detail_keeps_the_1h_count_after_its_summary_arrives(
    one_hour: int | None, expected: Decimal, reported: bool
) -> None:
    query = execution_timescale.TimescaleExecutionCostQuery(Mock())
    turns = [_grouped_row(_MILLION, one_hour)]
    summary = _summary_row(expected if reported else None)

    before = query._price_token_usage_groups(turns)
    after = query._price_session_summary_groups(
        [summary], _unreported(expected, one_hour, reported), turns
    )

    assert before.data.cache_creation_1h == (one_hour or 0)
    assert after.data.cache_creation_1h == before.data.cache_creation_1h
    assert after.total_cost == before.total_cost == expected


@pytest.mark.parametrize("reported", _REPORTED)
@pytest.mark.parametrize(("one_hour", "expected"), _COMPLETION_CASES)
def test_execution_list_keeps_the_1h_count_after_its_summary_arrives(
    one_hour: int | None, expected: Decimal, reported: bool
) -> None:
    query = execution_query_service.ExecutionCostQueryService(Mock())
    turns = [_grouped_row(_MILLION, one_hour)]
    summary = _summary_row(expected if reported else None)

    before = query._build_from_token_usage("exec-1", turns, {})
    after = query._build_from_summary(
        "exec-1", [summary], {}, {}, _unreported(expected, one_hour, reported), turns
    )

    assert before.cache_creation_1h_tokens == (one_hour or 0)
    assert after.cache_creation_1h_tokens == before.cache_creation_1h_tokens
    assert after.total_cost_usd == before.total_cost_usd == expected


@pytest.mark.parametrize("reader", ["list", "detail"])
@pytest.mark.parametrize("running_first", [False, True])
def test_execution_summary_excludes_running_sessions_1h_writes(
    reader: str, running_first: bool
) -> None:
    """A summary's total and TTL split must describe the same session set."""
    completed = _grouped_row(_MILLION, 0)
    running = _grouped_row(_MILLION, _MILLION, session_id="running")
    turns = [completed, running]
    if running_first:
        turns.reverse()
    summary = _summary_row(Decimal("5.00"))

    if reader == "list":
        query = execution_query_service.ExecutionCostQueryService(Mock())
        before = query._build_from_token_usage("exec-1", turns, {})
        after = query._build_from_summary("exec-1", [summary], {}, {}, turn_rows=turns)
        assert before.cache_creation_tokens == 2 * _MILLION
        assert before.cache_creation_1h_tokens == _MILLION
        assert before.total_cost_usd == Decimal("13.00")
        assert after.session_ids == ["session-1"]
        assert after.cache_creation_tokens == _MILLION
        assert after.cache_creation_1h_tokens == 0
        assert after.total_cost_usd == Decimal("5.00")
    else:
        detail = execution_timescale.TimescaleExecutionCostQuery(Mock())
        before_detail = detail._price_token_usage_groups(turns)
        after_detail = detail._price_session_summary_groups(
            [summary], execution_timescale.UnreportedSessionCosts(), turns
        )
        assert before_detail.data.cache_creation == 2 * _MILLION
        assert before_detail.data.cache_creation_1h == _MILLION
        assert before_detail.total_cost == Decimal("13.00")
        assert after_detail.data.session_ids == ["session-1"]
        assert after_detail.data.cache_creation == _MILLION
        assert after_detail.data.cache_creation_1h == 0
        assert after_detail.total_cost == Decimal("5.00")
