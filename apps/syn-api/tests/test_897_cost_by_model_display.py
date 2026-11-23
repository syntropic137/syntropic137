"""#897 slice N1: the model breakdown card's per-model text comes from the API.

The dashboard summed each phase's ``cost_by_model`` in the browser
(``aggregateCostByModel``), derived the "not yet attributed" remainder against
the scope's total (``ModelBreakdown``), and formatted every row itself. The
execution detail route now serves the summed ``cost_by_model``, and both it and
the session detail route serve ``cost_by_model_display`` and
``unattributed_cost_display``.

THE PARITY FIXTURE. ``PARITY_PHASES`` is one input with every case the
TypeScript distinguishes, and ``TS_AGGREGATE`` / ``TS_UNATTRIBUTED`` are what
``aggregateCostByModel`` and ``ModelBreakdown`` produce for it, worked by hand
from ``apps/syn-dashboard-ui/src/utils/exactUsd.ts`` (``parseExactUsd`` rounds to
18 places half away from zero and refuses what ``DECIMAL_RE`` does not match;
``exactUsdToString`` strips trailing zeros). It was read, not run: if the
TypeScript changes, this fixture is the claim to re-check.

WHY THE ROUTE TESTS WALK THE ROUTE. A phase's ``cost_by_model`` is set after the
phase model is built, by ``_enrich_costs``. An execution-level sum taken before
that hop is ``{}`` for every execution, so the split goes in as Lane 2 data and
is read off the JSON a client receives.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_api.cost_by_model_display import model_breakdown_text, sum_cost_by_model
from syn_api.routes.executions.models import ExecutionDetailResponse
from syn_api.routes.sessions import SessionResponse
from syn_api.types import Ok, SessionDetail
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_shared.display import format_cost

pytestmark = pytest.mark.unit

OPUS = "claude-opus-5"
SOL = "gpt-6-sol"
HAIKU = "claude-haiku-5"
SONNET = "claude-sonnet-5"
BAD = "claude-malformed"

PARITY_PHASES: list[dict[str, str]] = [
    {OPUS: "0.30566780000000005", SOL: "0.1"},
    # Unparseable values are skipped, never read as zero, including the
    # spellings Python's Decimal accepts and DECIMAL_RE refuses.
    {OPUS: "0.1324232", SOL: "not-a-number", HAIKU: "0", BAD: "NaN"},
    # A negative is summed, an exponent is read, and the 19th decimal place
    # rounds half away from zero: 5e-19 is one atto-dollar.
    {SOL: "-0.05", SONNET: "1E-7", OPUS: "0.0000000000000000005", BAD: "1_000"},
]

TS_AGGREGATE = {
    OPUS: "0.438091000000000051",
    SOL: "0.05",
    HAIKU: "0",
    SONNET: "0.0000001",
}
"""``aggregateCostByModel(PARITY_PHASES)``, in first-seen order. ``BAD`` never
parsed, so the TypeScript never set it."""

PARITY_TOTAL = Decimal("0.6")
TS_UNATTRIBUTED = Decimal("0.111908899999999949")
"""``ModelBreakdown``'s ``basis - attributed`` for ``TS_AGGREGATE`` against
``PARITY_TOTAL``: attributed sums the POSITIVE rows only (opus + sol + sonnet =
0.488091100000000051), so the zero haiku row adds nothing."""


def test_the_sum_matches_aggregate_cost_by_model() -> None:
    summed = sum_cost_by_model(PARITY_PHASES)

    assert summed == TS_AGGREGATE
    assert list(summed) == list(TS_AGGREGATE)


def test_the_unattributed_remainder_matches_model_breakdown() -> None:
    shown = model_breakdown_text(TS_AGGREGATE, PARITY_TOTAL)

    assert shown.unattributed_cost_display == format_cost(TS_UNATTRIBUTED) == "$0.11"


def test_each_model_reads_as_format_cost_renders_it() -> None:
    shown = model_breakdown_text(TS_AGGREGATE, PARITY_TOTAL)

    assert shown.cost_by_model_display == {
        OPUS: "$0.44",
        SOL: "$0.05",
        HAIKU: "$0.00",
        SONNET: "<$0.01",
    }
    for model, text in TS_AGGREGATE.items():
        assert shown.cost_by_model_display[model] == format_cost(Decimal(text))


def test_decimal_values_render_the_same_as_their_text() -> None:
    as_decimals = {model: Decimal(text) for model, text in TS_AGGREGATE.items()}

    assert model_breakdown_text(as_decimals, PARITY_TOTAL) == model_breakdown_text(
        TS_AGGREGATE, PARITY_TOTAL
    )


def test_no_split_is_empty_and_the_whole_total_is_unattributed() -> None:
    assert sum_cost_by_model([]) == {}
    assert sum_cost_by_model([{}, {}]) == {}

    shown = model_breakdown_text({}, Decimal("2.5"))

    assert shown.cost_by_model_display == {}
    assert shown.unattributed_cost_display == "$2.50"
    assert model_breakdown_text({}, Decimal("0")).unattributed_cost_display is None


@pytest.mark.parametrize(
    ("split", "total", "expected"),
    [
        ({OPUS: "1.25"}, Decimal("2.75"), "$1.50"),
        # Sub-cent but at the card's resolution: real money, shown.
        ({OPUS: "1"}, Decimal("1.0000005"), "<$0.01"),
        # Below it: rounding between two sums, which the card hides.
        ({OPUS: "1"}, Decimal("1.000000499999"), None),
        ({OPUS: "1.25", SOL: "0.5"}, Decimal("1.75"), None),
        # A total under what the rows account for never goes negative.
        ({OPUS: "1.25"}, Decimal("1"), None),
        # A negative row is not attribution: counting it would leave $0.50.
        ({OPUS: "1", SOL: "-0.5"}, Decimal("1"), None),
    ],
    ids=["positive", "sub-cent", "under-resolution", "zero", "negative", "negative-row"],
)
def test_unattributed_is_text_only_when_the_card_shows_a_row(
    split: dict[str, str], total: Decimal, expected: str | None
) -> None:
    assert model_breakdown_text(split, total).unattributed_cost_display == expected


# -- GET /executions/{id} ------------------------------------------------------

EXECUTION_ID = "exec-897-n1"
PLAN = "phase-plan"
IMPLEMENT = "phase-implement"


@dataclass
class _ExecutionCostProjection:
    cost: ExecutionCost

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost:
        return self.cost


@dataclass
class _Manager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection
    execution_cost: _ExecutionCostProjection


async def _served_execution(monkeypatch: pytest.MonkeyPatch) -> ExecutionDetailResponse:
    store = InMemoryProjectionStore()
    detail = WorkflowExecutionDetailProjection(store)
    await detail.on_workflow_execution_started(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-897",
            "workflow_name": "split",
            "started_at": "2026-11-23T10:00:00+00:00",
            "total_phases": 2,
        }
    )
    for phase_id in (PLAN, IMPLEMENT):
        await detail.on_phase_started(
            {
                "execution_id": EXECUTION_ID,
                "phase_id": phase_id,
                "phase_name": phase_id,
                "session_id": f"sess-{phase_id}",
                "started_at": "2026-11-23T10:00:05+00:00",
            }
        )
    by_phase = {
        PLAN: {OPUS: Decimal("0.30566780000000005"), SOL: Decimal("0.1")},
        IMPLEMENT: {OPUS: Decimal("0.1324232"), SONNET: Decimal("0.0000001")},
    }
    cost = ExecutionCost(
        execution_id=EXECUTION_ID,
        workflow_id="wf-897",
        session_count=2,
        session_ids=[f"sess-{PLAN}", f"sess-{IMPLEMENT}"],
        # More than the split: a third session's spend has no model yet.
        total_cost_usd=Decimal("2.6"),
        token_cost_usd=Decimal("2.6"),
        input_tokens=100,
        output_tokens=200,
        cost_by_phase={p: sum(m.values(), Decimal(0)) for p, m in by_phase.items()},
        models_by_phase=by_phase,
    )

    from syn_api import _wiring
    from syn_api.routes.executions import queries

    async def _noop_connect() -> None:
        return None

    manager = _Manager(store, detail, _ExecutionCostProjection(cost))
    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    response = await queries.get_execution_endpoint(EXECUTION_ID)
    return ExecutionDetailResponse.model_validate_json(response.model_dump_json())


@pytest.mark.anyio
async def test_the_execution_serves_its_phases_summed(monkeypatch: pytest.MonkeyPatch) -> None:
    body = await _served_execution(monkeypatch)

    # The read model stores each cost canonically, so the float tail of the
    # plan phase's opus cost is gone before the sum; the sum adds no noise back.
    assert body.cost_by_model == {
        OPUS: "0.438091",
        SOL: "0.1",
        SONNET: "0.0000001",
    }
    assert body.cost_by_model == sum_cost_by_model(p.cost_by_model for p in body.phases)


@pytest.mark.anyio
async def test_the_execution_serves_the_card_text(monkeypatch: pytest.MonkeyPatch) -> None:
    body = await _served_execution(monkeypatch)

    assert body.cost_by_model_display == {OPUS: "$0.44", SOL: "$0.10", SONNET: "<$0.01"}
    # 2.6 - (0.438091 + 0.1 + 0.0000001)
    assert body.unattributed_cost_display == format_cost(Decimal("2.0619089"))
    assert body.unattributed_cost_display == "$2.06"


@pytest.mark.anyio
async def test_each_phase_serves_its_own_card_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slice O: the phase card's per-model text, read off the served JSON."""
    body = await _served_execution(monkeypatch)
    phases = {p.phase_id: p for p in body.phases}

    assert phases[PLAN].cost_by_model_display == {OPUS: "$0.31", SOL: "$0.10"}
    assert phases[IMPLEMENT].cost_by_model_display == {OPUS: "$0.13", SONNET: "<$0.01"}
    for phase in body.phases:
        assert phase.cost_by_model_display == {
            model: format_cost(Decimal(cost)) for model, cost in phase.cost_by_model.items()
        }


# -- GET /sessions/{id} --------------------------------------------------------


async def _served_session(detail: SessionDetail) -> SessionResponse:
    from syn_api.routes.sessions import get_session_endpoint

    with (
        patch("syn_api.routes.sessions.get_projection_mgr", return_value=MagicMock()),
        patch("syn_api.prefix_resolver.resolve_or_raise", new=AsyncMock(return_value="sess-1")),
        patch("syn_api.routes.sessions.get_session", new=AsyncMock(return_value=Ok(detail))),
    ):
        response = await get_session_endpoint("sess-1")
    return SessionResponse.model_validate_json(response.model_dump_json())


async def test_the_session_serves_the_card_text() -> None:
    body = await _served_session(
        SessionDetail(
            id="sess-1",
            status="running",
            total_cost_usd=Decimal("1.75"),
            cost_by_model={OPUS: Decimal("1.2"), SONNET: Decimal("0.004")},
        )
    )

    assert body.cost_by_model_display == {OPUS: "$1.20", SONNET: "<$0.01"}
    assert body.unattributed_cost_display == format_cost(Decimal("0.546")) == "$0.55"


async def test_a_fully_attributed_session_has_no_remainder() -> None:
    body = await _served_session(
        SessionDetail(
            id="sess-1",
            status="completed",
            total_cost_usd=Decimal("1.204"),
            cost_by_model={OPUS: Decimal("1.2"), SONNET: Decimal("0.004")},
        )
    )

    assert body.cost_by_model_display == {OPUS: "$1.20", SONNET: "<$0.01"}
    assert body.unattributed_cost_display is None
