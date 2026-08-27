"""Unpriced work must not reach a client as ``$0.00`` (issue #890).

The domain layer has known the difference between "this was free" and "we could
not price this" since #788: ``ExecutionCost`` and ``SessionCost`` both carry
``unpriced_observation_count``. The API carriers between the read models and the
response models dropped it - ``_SummaryEnrichment``, ``_CostData``,
``_ExecutionEnrichment`` and ``_MergedExecutionTotals`` each held a cost and no
coverage - so every surface rendered an unpriced total as a confident zero.

These cases pin the whole hop: read model in, response model out, with the
rendered ``*_display`` string asserted rather than just the raw count. Asserting
only the count would let a future change carry the number correctly and still
print ``$0.00`` next to it.

They also go THROUGH the loaders (``_load_cost_data``, ``_enrich_costs``) rather
than hand-building an already-correct carrier and passing it to the mapper. An
earlier version of this file did the latter and stayed green while
``_load_cost_data`` silently dropped the count - a test that passes by not
executing the code it names is worse than no test, because it also retires the
suspicion.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_shared.display import format_cost

# A real OpenAI model with no rate in MODEL_PRICING_TABLE - the production shape
# of "unpriced", rather than an invented id that could never occur on the wire.
UNPRICED_MODEL = "gpt-5.6-mini"


def _unpriced_session_cost() -> SessionCost:
    """A completed session whose model has no rate: real tokens, no dollars."""
    cost = SessionCost(session_id="sess-890")
    cost.input_tokens = 35
    cost.output_tokens = 1_708
    cost.cache_read_tokens = 57_214
    cost.agent_model = UNPRICED_MODEL
    cost.total_cost_usd = Decimal("0")
    cost.token_cost_usd = Decimal("0")
    cost.unpriced_observation_count = 12
    cost.duration_ms = 36_000
    return cost


@dataclass
class _StubSessionCostQuery:
    """Stands in for ``SessionCostQueryService`` at the ``_load_cost_data`` seam."""

    cost: SessionCost | None

    async def get(self, session_id: str) -> SessionCost | None:
        return self.cost


def _patch_session_cost_query(monkeypatch: pytest.MonkeyPatch, cost: SessionCost | None) -> None:
    """Point ``_load_cost_data`` at a stubbed query service.

    Patching HERE rather than injecting a ready-made ``_CostData`` is the whole
    point: everything between the read model and the response - including the
    ``_CostData`` construction that dropped the count - stays under test.
    """
    from syn_api.routes import sessions

    monkeypatch.setattr(sessions, "get_session_cost_query", lambda: _StubSessionCostQuery(cost))


@pytest.mark.unit
class TestSessionDetailSurfacesUnpriced:
    """The detail endpoint's own path: ``_load_cost_data`` -> ``_CostData`` -> response."""

    @pytest.mark.asyncio
    async def test_load_cost_data_carries_the_count_off_the_read_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes.sessions import _load_cost_data

        _patch_session_cost_query(monkeypatch, _unpriced_session_cost())

        data = await _load_cost_data("sess-890", fallback_tokens=0, fallback_cost=Decimal("0"))

        assert data.unpriced_observation_count == 12

    @pytest.mark.asyncio
    async def test_detail_response_says_unpriced_not_zero_dollars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End to end for the most-viewed cost surface (#890)."""
        from syn_api.routes.sessions import _load_cost_data
        from syn_api.types import SessionDetail

        _patch_session_cost_query(monkeypatch, _unpriced_session_cost())
        data = await _load_cost_data("sess-890", fallback_tokens=0, fallback_cost=Decimal("0"))

        detail = SessionDetail(
            id="sess-890",
            status="completed",
            total_cost_usd=data.total_cost_usd,
            unpriced_observation_count=data.unpriced_observation_count,
            agent_model=data.agent_model,
        )
        rendered = format_cost(detail.total_cost_usd, detail.unpriced_observation_count)

        assert detail.unpriced_observation_count == 12
        assert rendered == "unpriced"
        assert rendered != "$0.00"

    @pytest.mark.asyncio
    async def test_a_priced_session_detail_still_renders_a_dollar_figure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The change must be invisible to sessions we can actually price."""
        from syn_api.routes.sessions import _load_cost_data

        cost = _unpriced_session_cost()
        cost.agent_model = "claude-sonnet-4-20250514"
        cost.total_cost_usd = Decimal("1.25")
        cost.unpriced_observation_count = 0
        _patch_session_cost_query(monkeypatch, cost)

        data = await _load_cost_data("sess-890", fallback_tokens=0, fallback_cost=Decimal("0"))

        assert data.unpriced_observation_count == 0
        assert format_cost(data.total_cost_usd, data.unpriced_observation_count) == "$1.25"


@pytest.mark.unit
class TestSessionSummarySurfacesUnpriced:
    def test_summary_response_says_unpriced_not_zero_dollars(self) -> None:
        from syn_api.routes.sessions import (
            _build_session_summary_response,
            _enrichment_from_cost,
        )
        from syn_api.types import SessionSummary

        enrichment = _enrichment_from_cost(_unpriced_session_cost())
        summary = SessionSummary(id="sess-890", status="completed")

        response = _build_session_summary_response(summary, None, enrichment)

        assert response.unpriced_observation_count == 12
        assert response.total_cost_display == "unpriced"
        assert response.total_cost_display != "$0.00"

    def test_priced_session_still_renders_a_dollar_figure(self) -> None:
        """The change must be invisible to sessions we can actually price."""
        from syn_api.routes.sessions import (
            _build_session_summary_response,
            _enrichment_from_cost,
        )
        from syn_api.types import SessionSummary

        cost = _unpriced_session_cost()
        cost.agent_model = "claude-sonnet-4-20250514"
        cost.total_cost_usd = Decimal("1.25")
        cost.unpriced_observation_count = 0

        response = _build_session_summary_response(
            SessionSummary(id="sess-890", status="completed"), None, _enrichment_from_cost(cost)
        )

        assert response.unpriced_observation_count == 0
        assert response.total_cost_display == "$1.25"

    def test_a_genuinely_free_session_still_renders_zero_dollars(self) -> None:
        """Zero is a legitimate answer when we KNOW it - only unknown is relabelled."""
        from syn_api.routes.sessions import (
            _build_session_summary_response,
            _enrichment_from_cost,
        )
        from syn_api.types import SessionSummary

        cost = SessionCost(session_id="sess-free")
        cost.agent_model = "claude-sonnet-4-20250514"

        response = _build_session_summary_response(
            SessionSummary(id="sess-free", status="completed"), None, _enrichment_from_cost(cost)
        )

        assert response.unpriced_observation_count == 0
        assert response.total_cost_display == "$0.00"


def _partly_unpriced_execution_cost() -> ExecutionCost:
    """An execution where one phase priced and another did not.

    The interesting case: the total is a real number AND incomplete, so it must
    render as a lower bound rather than as either a confident figure or nothing.
    """
    return ExecutionCost(
        execution_id="exec-890",
        workflow_id="wf-890",
        session_count=2,
        session_ids=["sess-a", "sess-b"],
        total_cost_usd=Decimal("3.50"),
        token_cost_usd=Decimal("3.50"),
        input_tokens=100,
        output_tokens=200,
        cost_by_phase={"plan": Decimal("3.50")},
        unpriced_by_phase={"implement": 9},
        unpriced_observation_count=9,
    )


@dataclass
class _StubExecutionCostProjection:
    cost: ExecutionCost

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost:
        return self.cost


@dataclass
class _StubProjectionManager:
    execution_cost: _StubExecutionCostProjection


@pytest.mark.unit
class TestExecutionSurfacesUnpriced:
    def test_summary_response_marks_a_partial_total_as_a_lower_bound(self) -> None:
        from syn_api.routes.executions.queries import (
            _build_execution_summary_response,
            _ExecutionEnrichment,
        )
        from syn_api.types import ExecutionSummary

        summary = ExecutionSummary(
            workflow_execution_id="exec-890",
            workflow_id="wf-890",
            workflow_name="partly-priced",
            status="completed",
            repos=[],
        )
        enrichment = _ExecutionEnrichment(
            total_cost_usd=Decimal("3.50"), unpriced_observation_count=9
        )

        response = _build_execution_summary_response(summary, enrichment)

        assert response.unpriced_observation_count == 9
        assert response.total_cost_display == ">=$3.50 (partial)"

    def test_summary_response_without_enrichment_carries_the_domain_count(self) -> None:
        """No Lane 2 record: the domain summary's own coverage must survive."""
        from syn_api.routes.executions.queries import _build_execution_summary_response
        from syn_api.types import ExecutionSummary

        summary = ExecutionSummary(
            workflow_execution_id="exec-890",
            workflow_id="wf-890",
            workflow_name="unpriced",
            status="completed",
            total_cost_usd=Decimal("0"),
            unpriced_observation_count=4,
            repos=[],
        )

        response = _build_execution_summary_response(summary, None)

        assert response.unpriced_observation_count == 4
        assert response.total_cost_display == "unpriced"

    @pytest.mark.asyncio
    async def test_enrich_costs_marks_the_unpriced_phase_not_just_the_priced_one(
        self,
    ) -> None:
        """Per phase, absence from ``cost_by_phase`` is not enough signal.

        A phase missing from the breakdown looks identical to a phase that spent
        nothing. ``unpriced_by_phase`` is what separates them.
        """
        from syn_api.routes.executions.queries import _enrich_costs
        from syn_api.types import PhaseExecution

        cost = _partly_unpriced_execution_cost()
        phases = [
            PhaseExecution(phase_id="plan", name="Plan", status="completed"),
            PhaseExecution(phase_id="implement", name="Implement", status="completed"),
            PhaseExecution(phase_id="review", name="Review", status="completed"),
        ]

        enriched = await _enrich_costs(
            cost.execution_id,
            _StubProjectionManager(_StubExecutionCostProjection(cost)),
            phases,
            fallback_tokens=0,
            fallback_cost=Decimal("0"),
        )

        by_id = {p.phase_id: p for p in phases}
        assert by_id["plan"].cost_usd == Decimal("3.50")
        assert by_id["plan"].unpriced_observation_count == 0
        # Unknown cost: no dollars, but explicitly flagged.
        assert by_id["implement"].cost_usd == Decimal("0")
        assert by_id["implement"].unpriced_observation_count == 9
        # Genuinely no spend: no dollars and nothing to flag.
        assert by_id["review"].cost_usd == Decimal("0")
        assert by_id["review"].unpriced_observation_count == 0
        assert enriched.unpriced_observation_count == 9
