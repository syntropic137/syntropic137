"""Cost is attributed to the model that RAN, never to an alias (ADR-067).

Three row shapes reach the cost readers:

- LEGACY: written before ADR-067, ``model`` holds the REQUESTED model (an
  alias such as ``opus``) and there is no ``requested_model`` key.
- NEW, REPORTED: ``model`` is what the harness said it ran, ``requested_model``
  the alias.
- NEW, UNREPORTED: ``model`` is null, ``requested_model`` the alias.

For each, the in-memory projections (fed observation ``data``) and the SQL row
mappers (fed rows shaped like the grouped queries' output) must agree - that is
what makes a replayed projection and a live query report the same thing - and:

- a legacy alias row is priced exactly as before, but its cost is filed under
  ``UNKNOWN_MODEL_KEY`` and its alias surfaces as ``requested_model``;
- a reported row is priced and filed under the reported id;
- ``agent_model`` is only ever a reported id.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions import CostCalculator, TokenUsageData
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    price_session_rows,
)
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import (
    UNATTRIBUTED_MODEL,
)
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    price_grouped_session_summary,
    price_grouped_token_usage,
    price_phase_rows,
)
from syn_shared.agents import ModelAlias, ModelId
from syn_shared.observed_model import UNKNOWN_MODEL_KEY

if TYPE_CHECKING:
    from collections.abc import Sequence

    import asyncpg

    from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
    from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

ALIAS = ModelAlias.OPUS
REPORTED = ModelId.CLAUDE_OPUS_5_5
#: Reported under an alias that points elsewhere, so pricing by the reported
#: model is visible in the numbers.
OTHER_REPORTED = ModelId.CLAUDE_SONNET_5

_SESSION = "sess-1"
_EXECUTION = "exec-1"
_PHASE = "phase-1"


def legacy(tokens: int, model: str = ALIAS) -> TokenUsageData:
    return TokenUsageData(
        input_tokens=tokens,
        output_tokens=tokens // 10,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        model=model,
    )


def reported(tokens: int, model: str = REPORTED) -> TokenUsageData:
    return TokenUsageData(
        input_tokens=tokens,
        output_tokens=tokens // 10,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        model=model,
        requested_model=ALIAS,
    )


def unreported(tokens: int) -> TokenUsageData:
    return TokenUsageData(
        input_tokens=tokens,
        output_tokens=tokens // 10,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        model=None,
        requested_model=ALIAS,
    )


def _alias_price(tokens: int) -> Decimal:
    pricing = CostCalculator().resolve_pricing(ALIAS)
    assert pricing is not None
    return pricing.calculate_cost(tokens, tokens // 10, 0, 0)


class _Store[RowT]:
    """The projection store, in memory; rows are opaque, as the real store treats them."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], RowT] = {}

    async def save(self, name: str, key: str, value: RowT) -> None:
        self._rows[(name, key)] = value

    async def get(self, name: str, key: str) -> RowT | None:
        return self._rows.get((name, key))


@dataclass(frozen=True)
class _Row:
    """The row the grouped SQL yields for one observation - model columns included.

    ``has_requested_model`` is ``data ? 'requested_model'`` in SQL: key
    PRESENCE, so a null requested model still marks the row as new.
    """

    model: str | None
    requested_model: str | None
    has_requested_model: bool
    total_input: int
    total_output: int
    model_column: str = "model"
    session_id: str = _SESSION
    execution_id: str = _EXECUTION
    phase_id: str = _PHASE
    cache_creation: int = 0
    cache_read: int = 0
    sdk_cost: Decimal | None = None
    observation_count: int = 1
    session_ids: tuple[str, ...] = (_SESSION,)

    def get(self, key: str, default: object = None) -> object:
        if key == self.model_column:
            return self.model
        if key == "session_ids":
            return list(self.session_ids)
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> object:
        return self.get(key)


def _sql_row(data: TokenUsageData, *, model_column: str = "model") -> _Row:
    return _Row(
        model=data["model"],
        requested_model=data.get("requested_model"),
        has_requested_model="requested_model" in data,
        total_input=data["input_tokens"],
        total_output=data["output_tokens"],
        model_column=model_column,
    )


def _records(rows: Sequence[_Row]) -> list[asyncpg.Record]:
    return list(rows)  # type: ignore[arg-type]  # answers every lookup a Record does here


async def _in_memory_session(*rows: TokenUsageData) -> SessionCost:
    projection = SessionCostProjection(store=_Store())  # type: ignore[arg-type]
    for data in rows:
        await projection.on_agent_observation(
            {
                "session_id": _SESSION,
                "execution_id": _EXECUTION,
                "phase_id": _PHASE,
                "event_type": "token_usage",
                "data": data,
            }
        )
    saved = await projection.get_session_cost(_SESSION)
    assert saved is not None
    return saved


async def _in_memory_execution(*rows: TokenUsageData) -> ExecutionCost:
    projection = ExecutionCostProjection(store=_Store())  # type: ignore[arg-type]
    for data in rows:
        await projection.on_agent_observation(
            {
                "session_id": _SESSION,
                "execution_id": _EXECUTION,
                "phase_id": _PHASE,
                "event_type": "token_usage",
                "data": data,
            }
        )
    saved = await projection.get_execution_cost(_EXECUTION)
    assert saved is not None
    return saved


class TestLegacyAliasRows:
    async def test_the_alias_is_the_request_and_the_cost_is_unchanged(self) -> None:
        saved = await _in_memory_session(legacy(1000))

        assert saved.agent_model is None
        assert saved.requested_model == ALIAS
        assert saved.cost_by_model == {UNKNOWN_MODEL_KEY: _alias_price(1000)}
        assert saved.total_cost_usd == _alias_price(1000)
        assert saved.unpriced_observation_count == 0

    async def test_the_sql_path_reads_it_the_same_way(self) -> None:
        totals = price_session_rows(
            _records([_sql_row(legacy(1000), model_column="agent_model")]),
            CostCalculator(),
            _SESSION,
        )
        assert totals is not None
        assert totals.primary_model is None
        assert totals.requested_model == ALIAS
        assert totals.cost_by_model == {UNKNOWN_MODEL_KEY: _alias_price(1000)}

    async def test_an_explicit_legacy_id_is_kept_as_what_ran(self) -> None:
        """Delegate imports and old pinned ids were never aliases."""
        saved = await _in_memory_session(legacy(1000, model=REPORTED))
        assert saved.agent_model == REPORTED
        assert set(saved.cost_by_model) == {REPORTED}

    async def test_the_execution_breakdown_files_it_as_unknown(self) -> None:
        saved = await _in_memory_execution(legacy(1000))
        assert saved.cost_by_model == {UNKNOWN_MODEL_KEY: _alias_price(1000)}

        grouped = price_grouped_token_usage((_records([_sql_row(legacy(1000))])), CostCalculator())
        assert grouped.cost_by_model == {UNKNOWN_MODEL_KEY: _alias_price(1000)}
        assert grouped.total_cost == _alias_price(1000)


class TestNewRows:
    async def test_a_reported_row_is_filed_under_what_ran(self) -> None:
        saved = await _in_memory_session(reported(1000))

        assert saved.agent_model == REPORTED
        assert saved.requested_model == ALIAS
        assert set(saved.cost_by_model) == {REPORTED}

    async def test_a_row_is_priced_as_the_reported_model_not_the_alias(self) -> None:
        other = CostCalculator().resolve_pricing(OTHER_REPORTED)
        assert other is not None
        expected = other.calculate_cost(1000, 100, 0, 0)
        assert expected != _alias_price(1000), "the fixture must make the choice visible"

        saved = await _in_memory_session(reported(1000, model=OTHER_REPORTED))
        assert saved.cost_by_model == {OTHER_REPORTED: expected}

    async def test_an_unreported_row_is_unknown_and_priced_as_requested(self) -> None:
        saved = await _in_memory_session(unreported(1000))

        assert saved.agent_model is None
        assert saved.requested_model == ALIAS
        assert saved.cost_by_model == {UNKNOWN_MODEL_KEY: _alias_price(1000)}

    async def test_the_primary_model_is_chosen_among_reported_models_only(self) -> None:
        """Most unreported tokens never make the alias (or "unknown") primary."""
        saved = await _in_memory_session(unreported(9000), reported(10, model=OTHER_REPORTED))
        assert saved.agent_model == OTHER_REPORTED


MIXED: tuple[TokenUsageData, ...] = (
    legacy(1000),
    legacy(700, model=REPORTED),
    reported(300),
    reported(200, model=OTHER_REPORTED),
    unreported(500),
)


class TestReplayAndQueryAgree:
    """The same stored rows, two readers, one answer."""

    async def test_session_cost(self) -> None:
        saved = await _in_memory_session(*MIXED)
        totals = price_session_rows(
            _records([_sql_row(row, model_column="agent_model") for row in MIXED]),
            CostCalculator(),
            _SESSION,
        )
        assert totals is not None

        assert saved.cost_by_model == totals.cost_by_model
        assert saved.total_cost_usd == totals.total_cost
        assert saved.agent_model == totals.primary_model
        assert saved.requested_model == totals.requested_model
        assert saved.tokens_by_model == totals.tokens_by_model
        assert UNKNOWN_MODEL_KEY not in totals.tokens_by_model
        assert ALIAS not in totals.cost_by_model

    async def test_execution_cost(self) -> None:
        saved = await _in_memory_execution(*MIXED)
        grouped = price_grouped_token_usage(
            (_records([_sql_row(row) for row in MIXED])), CostCalculator()
        )

        assert saved.cost_by_model == grouped.cost_by_model
        assert saved.total_cost_usd == grouped.total_cost
        assert ALIAS not in grouped.cost_by_model

    async def test_summary_rows_and_phase_breakdown_use_the_same_keys(self) -> None:
        """The session_summary readers classify exactly as the token readers do."""
        rows = [_sql_row(row) for row in MIXED]
        grouped = price_grouped_token_usage((_records(rows)), CostCalculator())
        summary = price_grouped_session_summary((_records(rows)), CostCalculator())
        phases = price_phase_rows(_records(rows), CostCalculator())

        assert summary.cost_by_model == grouped.cost_by_model
        assert phases.models_by_phase[_PHASE] == grouped.cost_by_model
        assert UNATTRIBUTED_MODEL == UNKNOWN_MODEL_KEY


class TestSummaryAfterTurns:
    async def test_replay_attributes_the_summary_cost_as_the_sql_path_does(self) -> None:
        """Turn rows estimate one cost; the summary reports another. The
        breakdown must follow the summary, as the SQL path (which reads only
        the summary row) does - never keep the superseded turn estimate."""
        projection = SessionCostProjection(store=_Store())  # type: ignore[arg-type]
        base = {"session_id": _SESSION, "execution_id": _EXECUTION, "phase_id": _PHASE}
        await projection.on_agent_observation(
            {**base, "event_type": "token_usage", "data": reported(1000)}
        )
        await projection.on_session_summary(
            {
                **base,
                "data": {
                    "total_cost_usd": 0.5,
                    "total_input_tokens": 1000,
                    "total_output_tokens": 100,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "num_turns": 1,
                    "duration_ms": 10,
                    "model": REPORTED,
                    "requested_model": ALIAS,
                    "totals_are_authoritative": True,
                },
            }
        )
        saved = await projection.get_session_cost(_SESSION)
        assert saved is not None

        assert saved.total_cost_usd == Decimal("0.5")
        assert saved.cost_by_model == {REPORTED: Decimal("0.5")}
