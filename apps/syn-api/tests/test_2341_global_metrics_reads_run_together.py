"""Global GET /metrics runs its four independent reads together (#2341).

At the #2341 scale the reads summed past the 100ms p95 budget on CI; run
together they cost the slowest one. Each takes its own pooled connection, so
the response is the same either way. This pins the overlap itself: every read
waits at a barrier that only opens once all four have started, so reads run in
turn never get past the first one.
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions import CanonicalTotals

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

_READS = 4


@pytest.fixture(autouse=True)
def _reset_storage():
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


@pytest.mark.asyncio
async def test_the_global_reads_are_all_in_flight_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api.routes import metrics

    barrier = asyncio.Barrier(_READS)
    started: list[str] = []

    async def _arrive(name: str) -> None:
        started.append(name)
        # Reads awaited one after another strand the first here: the barrier
        # needs all four to have started before any can finish.
        await asyncio.wait_for(barrier.wait(), timeout=2)

    async def status_counts(workflow_id: str | None) -> metrics.ExecutionStatusCounts:
        await _arrive("status_counts")
        return metrics.ExecutionStatusCounts(completed=2, failed=1)

    async def session_count(workflow_id: str | None) -> int:
        await _arrive("sessions")
        return 5

    async def artifact_count(workflow_id: str | None) -> int:
        await _arrive("artifacts")
        return 3

    async def canonical_totals(execution_ids: set[str] | None) -> CanonicalTotals:
        await _arrive("totals")
        return CanonicalTotals(cost_usd=Decimal("1.25"), input_tokens=10)

    monkeypatch.setattr(metrics, "_execution_status_counts", status_counts)
    monkeypatch.setattr(metrics, "_session_count", session_count)
    monkeypatch.setattr(metrics, "_artifact_count", artifact_count)
    monkeypatch.setattr(metrics, "_canonical_totals", canonical_totals)

    body = (await metrics.get_metrics_endpoint(workflow_id=None)).model_dump(mode="json")

    assert sorted(started) == ["artifacts", "sessions", "status_counts", "totals"]
    # The values still land in their own fields: concurrency changed the timing only.
    assert body["completed_workflows"] == 2
    assert body["failed_workflows"] == 1
    assert body["total_sessions"] == 5
    assert body["total_artifacts"] == 3
    assert body["total_input_tokens"] == 10
    assert body["total_cost_display"] == "$1.25"


@pytest.mark.asyncio
async def test_one_unavailable_read_is_still_a_503(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from syn_api.routes import metrics

    async def fine(workflow_id: str | None) -> int:
        return 0

    async def broken(execution_ids: set[str] | None) -> CanonicalTotals:
        raise metrics.MetricsUnavailableError("canonical totals could not be read")

    monkeypatch.setattr(metrics, "_session_count", fine)
    monkeypatch.setattr(metrics, "_artifact_count", fine)
    monkeypatch.setattr(metrics, "_canonical_totals", broken)

    with pytest.raises(HTTPException) as caught:
        await metrics.get_metrics_endpoint(workflow_id=None)

    assert caught.value.status_code == 503
    assert "canonical totals could not be read" in str(caught.value.detail)
