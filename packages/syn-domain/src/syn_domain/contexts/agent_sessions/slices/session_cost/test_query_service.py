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
    SessionCostQueryService,
)

_FakeRow = Mapping[str, object]

_OPUS_MODEL = "claude-opus-4-20250514"
_SONNET_MODEL = "claude-sonnet-4-20250514"

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

    def test_unknown_model_contributes_zero_not_a_guess(self) -> None:
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_summary(_summary_row(None), tool_counts={}, started_map={})

        assert result.total_cost_usd == Decimal("0")
        assert result.cost_by_model == {}
        assert result.agent_model is None


@pytest.mark.unit
class TestBuildFromTokenUsagePricesByModel:
    def test_opus_session_prices_as_opus_not_sonnet(self) -> None:
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_token_usage(
            _token_usage_row(_OPUS_MODEL), tool_counts={}, started_map={}
        )

        assert result.total_cost_usd == _OPUS_COST_1M_1M
        assert result.total_cost_usd != _SONNET_COST_1M_1M
        assert result.cost_by_model == {_OPUS_MODEL: _OPUS_COST_1M_1M}

    def test_unknown_model_contributes_zero_not_a_guess(self) -> None:
        service = SessionCostQueryService(pool=None)  # type: ignore[arg-type]

        result = service._build_from_token_usage(
            _token_usage_row(None), tool_counts={}, started_map={}
        )

        assert result.total_cost_usd == Decimal("0")
        assert result.cost_by_model == {}
