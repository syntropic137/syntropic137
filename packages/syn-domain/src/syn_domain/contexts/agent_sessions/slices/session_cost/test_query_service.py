"""Regression tests: SessionCostQueryService prices non-Sonnet models correctly.

Issue #788 found that ``_resolve_cost``/``_build_from_summary``/
``_build_from_token_usage`` never passed ``agent_model`` (already selected in
the row as ``agent_model``) into ``calculate_token_cost``, so every session
priced from raw token counts (no SDK-reported ``total_cost_usd``) fell
through to the Sonnet default. These tests pin an Opus session pricing as
Opus - not Sonnet, not $0 - and confirm a genuinely unknown model still
contributes $0 without guessing.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
    _LIST_ALL_FROM_SUMMARY_QUERY,
    _LIST_ALL_FROM_TOKEN_USAGE_QUERY,
    _STARTED_AT_BY_SESSION_QUERY,
    _TOOL_COUNT_BY_SESSION_QUERY,
    SessionCostQueryService,
)

_FakeRow = Mapping[str, object]

_OPUS_MODEL = "claude-opus-4-20250514"
_SONNET_MODEL = "claude-sonnet-4-20250514"
# A real OpenAI model with no rate in the pricing table - the production shape
# of "unpriced", as opposed to an invented model id that could never occur.
_UNPRICED_REAL_MODEL = "gpt-5.6-mini"

# 1M input + 1M output tokens at Opus rates: $15.00 + $75.00 = $90.00
_OPUS_COST_1M_1M = Decimal("90.00")
# The same token counts at Sonnet rates would be $3.00 + $15.00 = $18.00 -
# this is the wrong answer the pre-fix code silently produced.
_SONNET_COST_1M_1M = Decimal("18.00")


def _summary_row(agent_model: str | None) -> _FakeRow:
    return {
        "session_id": "session-1",
        "total_input": 1_000_000,
        "total_output": 1_000_000,
        "cache_creation": 0,
        "cache_read": 0,
        "sdk_cost": None,  # no SDK-reported cost - must price from tokens
        "duration_ms_val": 0,
        "agent_model": agent_model,
        "num_turns": 1,
        "tool_count": 0,
        "completed_at": None,
        "execution_id": "exec-1",
        "phase_id": "phase-1",
    }


def _token_usage_row(agent_model: str | None) -> _FakeRow:
    return {
        "session_id": "session-2",
        "total_input": 1_000_000,
        "total_output": 1_000_000,
        "cache_creation": 0,
        "cache_read": 0,
        "started_at": None,
        "last_observation": None,
        "agent_model": agent_model,
        "execution_id": "exec-2",
        "phase_id": "phase-2",
        "observation_count": 7,
    }


@pytest.mark.unit
class TestBuildFromSummaryPricesByModel:
    def test_opus_session_prices_as_opus_not_sonnet(self) -> None:
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_summary(
            _summary_row(_OPUS_MODEL), tool_counts={}, started_map={}
        )

        assert result.total_cost_usd == _OPUS_COST_1M_1M
        assert result.total_cost_usd != _SONNET_COST_1M_1M
        assert result.cost_by_model == {_OPUS_MODEL: _OPUS_COST_1M_1M}
        assert result.agent_model == _OPUS_MODEL
        assert result.unpriced_observation_count == 0

    def test_unknown_model_contributes_zero_not_a_guess(self) -> None:
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_summary(_summary_row(None), tool_counts={}, started_map={})

        assert result.total_cost_usd == Decimal("0")
        assert result.cost_by_model == {}
        assert result.agent_model is None

    def test_unpriced_model_marks_the_zero_as_unpriced(self) -> None:
        """The zero must arrive labelled, or it reads as "this was free" (#890)."""
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_summary(
            _summary_row(_UNPRICED_REAL_MODEL), tool_counts={}, started_map={}
        )

        assert result.total_cost_usd == Decimal("0")
        assert result.unpriced_observation_count > 0
        # The model is still reported - we know WHAT ran, just not its rate.
        assert result.agent_model == _UNPRICED_REAL_MODEL
        # ...but it must not appear in the breakdown claiming to have cost $0.
        assert result.cost_by_model == {}


@pytest.mark.unit
class TestBuildFromTokenUsagePricesByModel:
    """``_build_from_token_usage`` now takes this session's model-grouped rows.

    The query groups by (session, model), so one session can produce several
    rows. Passing them as a list is what lets each be priced with its own rate.
    """

    def test_opus_session_prices_as_opus_not_sonnet(self) -> None:
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_token_usage(
            "session-2", [_token_usage_row(_OPUS_MODEL)], tool_counts={}, started_map={}
        )

        assert result is not None
        assert result.total_cost_usd == _OPUS_COST_1M_1M
        assert result.total_cost_usd != _SONNET_COST_1M_1M
        assert result.cost_by_model == {_OPUS_MODEL: _OPUS_COST_1M_1M}
        assert result.unpriced_observation_count == 0

    def test_unknown_model_contributes_zero_not_a_guess(self) -> None:
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_token_usage(
            "session-2", [_token_usage_row(None)], tool_counts={}, started_map={}
        )

        assert result is not None
        assert result.total_cost_usd == Decimal("0")
        assert result.cost_by_model == {}

    def test_unpriced_model_counts_real_observations_not_one(self) -> None:
        """The count reports the work that went unpriced, not the row count (#890)."""
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_token_usage(
            "session-2",
            [_token_usage_row(_UNPRICED_REAL_MODEL)],
            tool_counts={},
            started_map={},
        )

        assert result is not None
        assert result.total_cost_usd == Decimal("0")
        # The fixture row aggregates 7 token_usage observations.
        assert result.unpriced_observation_count == 7
        assert result.cost_by_model == {}

    def test_mixed_model_session_prices_each_group_with_its_own_rate(self) -> None:
        """One session, two models: price what we can, count what we cannot (#890).

        Under the old ``MAX(data->>'model')`` shape this session came back
        either as $90 with zero unpriced (the unknown tokens billed at Opus
        rates) or as $0 entirely unpriced, depending on which id sorted last.
        """
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_token_usage(
            "session-2",
            [_token_usage_row(_OPUS_MODEL), _token_usage_row(_UNPRICED_REAL_MODEL)],
            tool_counts={},
            started_map={},
        )

        assert result is not None
        assert result.total_cost_usd == _OPUS_COST_1M_1M
        assert result.unpriced_observation_count == 7
        assert result.cost_by_model == {_OPUS_MODEL: _OPUS_COST_1M_1M}
        # Tokens from both groups are real work and must both be reported.
        assert result.input_tokens == 2_000_000
        assert result.output_tokens == 2_000_000


class _StubConnection:
    """Dispatches ``fetch`` by query text, so row shapes stay tied to their SQL.

    The alternative - a single canned list - would let a test pass while the
    service read the wrong query for the wrong purpose.
    """

    def __init__(
        self,
        summary_rows: list[_FakeRow],
        token_rows: list[_FakeRow],
        tool_rows: list[_FakeRow],
        started_rows: list[_FakeRow],
    ) -> None:
        self._by_query = {
            _LIST_ALL_FROM_SUMMARY_QUERY: summary_rows,
            _LIST_ALL_FROM_TOKEN_USAGE_QUERY: token_rows,
            _TOOL_COUNT_BY_SESSION_QUERY: tool_rows,
            _STARTED_AT_BY_SESSION_QUERY: started_rows,
        }

    async def fetch(self, query: str, *_args: object) -> list[_FakeRow]:
        return self._by_query[query]


class _StubAcquire:
    def __init__(self, conn: _StubConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _StubConnection:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _StubPool:
    def __init__(self, conn: _StubConnection) -> None:
        self._conn = conn

    def acquire(self) -> _StubAcquire:
        return _StubAcquire(self._conn)


def _list_token_row(
    session_id: str,
    agent_model: str | None,
    *,
    observation_count: int = 7,
) -> _FakeRow:
    """A row from _LIST_ALL_FROM_TOKEN_USAGE_QUERY: one per (session, model)."""
    return {
        "session_id": session_id,
        "agent_model": agent_model,
        "total_input": 1_000_000,
        "total_output": 1_000_000,
        "cache_creation": 0,
        "cache_read": 0,
        "started_at": None,
        "last_observation": None,
        "observation_count": observation_count,
        "execution_id": "exec-1",
        "phase_id": "phase-1",
    }


def _list_summary_row(session_id: str, agent_model: str | None) -> _FakeRow:
    """A row from _LIST_ALL_FROM_SUMMARY_QUERY."""
    return {
        "session_id": session_id,
        "total_input": 1_000_000,
        "total_output": 1_000_000,
        "cache_creation": 0,
        "cache_read": 0,
        "sdk_cost": None,
        "duration_ms_val": 0,
        "agent_model": agent_model,
        "num_turns": 1,
        "tool_count": 0,
        "completed_at": None,
        "execution_id": "exec-1",
        "phase_id": "phase-1",
    }


@pytest.mark.unit
class TestListAllRegroupsRowsPerSession:
    """``list_all`` owns the regrouping, and nothing else exercised it.

    Every other case in this file calls ``_build_from_token_usage`` with an
    already-regrouped list, so removing the regroup entirely - and emitting one
    SessionCost per (session, model) row - would leave the suite green while
    silently duplicating every mixed-model session in the API response.

    Rows are interleaved across sessions on purpose: the SQL groups by
    (session_id, model) with no ORDER BY, so contiguous-per-session is not a
    guarantee the service may rely on.
    """

    @staticmethod
    def _service() -> SessionCostQueryService:
        conn = _StubConnection(
            summary_rows=[_list_summary_row("session-summarized", _SONNET_MODEL)],
            token_rows=[
                # Interleaved, and the summarized session also has live rows
                # that must NOT produce a second record.
                _list_token_row("session-mixed", _OPUS_MODEL),
                _list_token_row("session-summarized", _OPUS_MODEL),
                _list_token_row("session-solo", _OPUS_MODEL),
                _list_token_row("session-mixed", _UNPRICED_REAL_MODEL),
            ],
            tool_rows=[],
            started_rows=[],
        )
        return SessionCostQueryService(pool=_StubPool(conn))  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_emits_exactly_one_record_per_session(self) -> None:
        results = await self._service().list_all()

        ids = sorted(r.session_id for r in results)
        assert ids == ["session-mixed", "session-solo", "session-summarized"]
        # Four token rows plus one summary row must not become five records.
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_mixed_model_session_is_merged_not_duplicated(self) -> None:
        results = await self._service().list_all()
        mixed = next(r for r in results if r.session_id == "session-mixed")

        # Opus group priced, unpriced group counted - in ONE record.
        assert mixed.total_cost_usd == _OPUS_COST_1M_1M
        assert mixed.unpriced_observation_count == 7
        assert mixed.cost_by_model == {_OPUS_MODEL: _OPUS_COST_1M_1M}
        # Both groups' tokens are present, which is what proves they merged
        # rather than one row winning.
        assert mixed.input_tokens == 2_000_000

    @pytest.mark.asyncio
    async def test_summarized_session_ignores_its_live_token_rows(self) -> None:
        """The summary is authoritative; its token_usage rows must be excluded."""
        results = await self._service().list_all()
        summarized = [r for r in results if r.session_id == "session-summarized"]

        assert len(summarized) == 1
        # Priced as Sonnet from the summary, not as Opus from the token row.
        assert summarized[0].total_cost_usd == _SONNET_COST_1M_1M
        assert summarized[0].is_finalized is True
