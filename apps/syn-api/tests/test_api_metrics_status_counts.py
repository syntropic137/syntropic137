"""GET /metrics reports executions by every status, not only completed and failed.

The dashboard's status pie read ``completed_workflows`` and ``failed_workflows``
and nothing else, so cancelled, interrupted and still-running executions were
invisible. ``execution_status_counts`` is tallied from the same read model the
execution list counts its ``status_counts`` facet over, so the pie and the list
cannot disagree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi import HTTPException

from syn_domain.contexts.agent_sessions import CanonicalTotals
from syn_domain.contexts.orchestration import ExecutionStatus

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")


@dataclass
class _FakeCanonicalQuery:
    async def totals(self, execution_ids: set[str] | None = None) -> CanonicalTotals:
        return CanonicalTotals(cost_usd=Decimal("0"))


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


# One execution per terminal fate, plus runs still in flight, across two workflows.
_FATES = {
    "exec-c1": ("wf-a", "completed"),
    "exec-c2": ("wf-a", "completed"),
    "exec-c3": ("wf-b", "completed"),
    "exec-f1": ("wf-a", "failed"),
    "exec-x1": ("wf-a", "cancelled"),
    "exec-x2": ("wf-b", "cancelled"),
    "exec-i1": ("wf-b", "interrupted"),
    "exec-r1": ("wf-a", "running"),
}


async def _record_executions() -> None:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    projection = get_projection_mgr().workflow_execution_list
    for execution_id, (workflow_id, fate) in _FATES.items():
        await projection.on_workflow_execution_started(
            {
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "workflow_name": workflow_id,
                "started_at": "2026-10-01T00:00:00+00:00",
            }
        )
        event = {"execution_id": execution_id}
        if fate == "completed":
            await projection.on_workflow_completed(event)
        elif fate == "failed":
            await projection.on_workflow_failed(event)
        elif fate == "cancelled":
            await projection.on_execution_cancelled(event)
        elif fate == "interrupted":
            await projection.on_workflow_interrupted(event)


def test_the_counts_name_exactly_the_domain_statuses() -> None:
    from syn_api.routes.metrics import ExecutionStatusCounts

    assert set(ExecutionStatusCounts.model_fields) == {s.value for s in ExecutionStatus}


@pytest.mark.asyncio
async def test_status_counts_match_the_execution_store(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api._wiring import get_projection_mgr
    from syn_api.routes import metrics

    monkeypatch.setattr(metrics, "get_canonical_usage_query", _FakeCanonicalQuery)
    await _record_executions()

    body = (await metrics.get_metrics_endpoint(workflow_id=None)).model_dump(mode="json")

    assert body["execution_status_counts"] == {
        "not_started": 0,
        "running": 1,
        "completed": 3,
        "failed": 1,
        "cancelled": 2,
        "interrupted": 1,
    }
    # The same tally the execution list serves as its facet, field for field.
    page = await get_projection_mgr().workflow_execution_list.page()
    for status, count in page.status_counts.items():
        assert body["execution_status_counts"][status] == count
    assert sum(body["execution_status_counts"].values()) == page.total == len(_FATES)


@pytest.mark.asyncio
async def test_status_counts_narrow_to_the_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api.routes import metrics

    monkeypatch.setattr(metrics, "get_canonical_usage_query", _FakeCanonicalQuery)
    monkeypatch.setattr(metrics, "_build_phase_metrics", _no_phases)
    await _record_executions()

    body = (await metrics.get_metrics_endpoint(workflow_id="wf-b")).model_dump(mode="json")

    assert body["execution_status_counts"] == {
        "not_started": 0,
        "running": 0,
        "completed": 1,
        "failed": 0,
        "cancelled": 1,
        "interrupted": 1,
    }


async def _no_phases(workflow_id: str, execution_ids: set[str]) -> list[object]:
    return []


@pytest.mark.asyncio
async def test_a_status_outside_the_vocabulary_is_unavailable_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api._wiring import get_projection_mgr
    from syn_api.routes import metrics

    monkeypatch.setattr(metrics, "get_canonical_usage_query", _FakeCanonicalQuery)
    await _record_executions()
    projection = get_projection_mgr().workflow_execution_list
    record = await projection._store.get(projection.PROJECTION_NAME, "exec-r1")
    record["status"] = "paused"
    await projection._store.save(projection.PROJECTION_NAME, "exec-r1", record)

    with pytest.raises(HTTPException) as exc_info:
        await metrics.get_metrics_endpoint(workflow_id=None)
    assert exc_info.value.status_code == 503
