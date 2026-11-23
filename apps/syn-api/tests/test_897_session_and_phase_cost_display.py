"""Session detail and per-phase cost text come from the API (#897 slice M).

The dashboard used to format these two dollar figures itself. It now renders
``SessionResponse.total_cost_display`` and ``PhaseMetrics.cost_display``
verbatim, so each must be exactly what ``format_cost`` makes of the figure
beside it and its unpriced count, for all three coverage states. Asserted on
what the endpoint and the phase builder hand back, not on the models.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.types import Ok, SessionDetail
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_shared.display import format_cost

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

WORKFLOW = "wf-cost-display"


@dataclass(frozen=True)
class _Coverage:
    usd: Decimal
    unpriced: int
    expected: str


# One per state the UI used to branch on; the literal is what a reader sees.
COVERAGE = {
    "fully priced": _Coverage(Decimal("1.25"), 0, "$1.25"),
    "partially unpriced": _Coverage(Decimal("0.42"), 3, ">=$0.42 (partial)"),
    "all unpriced": _Coverage(Decimal("0"), 5, "unpriced"),
}


@pytest.mark.parametrize("case", COVERAGE.values(), ids=COVERAGE.keys())
async def test_session_detail_display_is_format_cost(case: _Coverage) -> None:
    from syn_api.routes.sessions import get_session_endpoint

    detail = SessionDetail(
        id="sess-1",
        status="completed",
        total_cost_usd=case.usd,
        unpriced_observation_count=case.unpriced,
    )
    with (
        patch("syn_api.routes.sessions.get_projection_mgr", return_value=MagicMock()),
        patch("syn_api.prefix_resolver.resolve_or_raise", new=AsyncMock(return_value="sess-1")),
        patch("syn_api.routes.sessions.get_session", new=AsyncMock(return_value=Ok(detail))),
    ):
        response = await get_session_endpoint("sess-1")

    body = response.model_dump(mode="json")
    assert body["total_cost_display"] == case.expected
    assert body["total_cost_display"] == format_cost(case.usd, case.unpriced)


@pytest.fixture
def _clean_projections():
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


@pytest.mark.usefixtures("_clean_projections")
async def test_phase_metrics_display_is_format_cost_per_phase() -> None:
    from syn_api._wiring import ensure_connected, get_projection_mgr
    from syn_api.routes import metrics

    await ensure_connected()
    projection = get_projection_mgr().workflow_phase_metrics
    phase_ids = {name: name.replace(" ", "-") for name in COVERAGE}
    for phase_id in phase_ids.values():
        await projection.on_phase_started(
            {
                "workflow_id": WORKFLOW,
                "phase_id": phase_id,
                "phase_name": phase_id,
                "started_at": "2026-11-23T00:00:00+00:00",
            }
        )
    cost = ExecutionCost(
        execution_id="exec-1",
        cost_by_phase={
            phase_ids[name]: case.usd for name, case in COVERAGE.items() if case.usd
        },
        unpriced_by_phase={
            phase_ids[name]: case.unpriced for name, case in COVERAGE.items() if case.unpriced
        },
    )

    phases = {p.phase_id: p for p in await metrics._build_phase_metrics(WORKFLOW, [cost])}

    for name, case in COVERAGE.items():
        body = phases[phase_ids[name]].model_dump(mode="json")
        assert body["cost_display"] == case.expected, name
        assert body["cost_display"] == format_cost(case.usd, case.unpriced), name
