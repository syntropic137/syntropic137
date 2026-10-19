"""#1881: resume lineage reaches `GET /executions/{id}` and the list rows.

A real resume chain (A -> B -> C, written by the domain's own resume path)
dispatched through the real coordinator into the real projections, then read
out of the HTTP response models. A field dropped at any hop between the read
model and the response would leave a failed parent reading `failed` with no
pointer forward, which is what the issue reports.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)
from syn_domain.contexts.orchestration.slices.start_resume.test_1696_a_resumed_start_reaches_the_execution_read_models import (
    RESUME_OF_RESUME,
    _coordinator,
    _history,
)
from syn_domain.contexts.orchestration.slices.start_resume.test_start_resume import (
    PARENT,
    RESUME,
)

pytestmark = pytest.mark.unit

A, B, C = PARENT, RESUME, RESUME_OF_RESUME


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


async def _store() -> InMemoryProjectionStore:
    store = InMemoryProjectionStore()
    coordinator = _coordinator(store)
    for envelope in await _history():
        await coordinator.dispatch_event(envelope)
    return store


@pytest.mark.asyncio
async def test_every_member_of_a_chain_links_both_ways(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = await _store()
    manager = _StubProjectionManager(
        store=store, workflow_execution_detail=WorkflowExecutionDetailProjection(store)
    )

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)

    a = (await queries.get_execution_endpoint(A)).model_dump(mode="json")
    b = (await queries.get_execution_endpoint(B)).model_dump(mode="json")
    c = (await queries.get_execution_endpoint(C)).model_dump(mode="json")

    # The failed root points at its child AND at the end of the chain.
    assert a["status"] == "failed"
    assert (a["resumed_from"], a["resumed_as"], a["latest_resumed_as"]) == (None, B, C)
    assert a["resumed_as_display"] == f"Resumed as {B}; latest continuation {C}"
    assert a["resumed_from_display"] is None

    assert b["resumed_from"]["parent_execution_id"] == A
    assert (b["resumed_as"], b["latest_resumed_as"]) == (C, C)
    assert b["resumed_as_display"] == f"Resumed as {C}"
    phase = b["resumed_from"]["resume_phase_id"]
    assert b["resumed_from_display"] == f"Resumed from {A} at phase {phase}"

    assert c["resumed_from"]["parent_execution_id"] == B
    assert (c["resumed_as"], c["latest_resumed_as"], c["resumed_as_display"]) == (None, None, None)


@pytest.mark.asyncio
async def test_a_list_row_carries_both_directions() -> None:
    from syn_api.routes.executions import queries

    store = await _store()
    rows = {
        r["workflow_execution_id"]: WorkflowExecutionSummary.from_dict(r)
        for r in await store.get_all(WorkflowExecutionListProjection.PROJECTION_NAME)
    }
    body = {
        k: queries._build_execution_summary_response(
            queries._to_execution_summary(v, {})
        ).model_dump(mode="json")
        for k, v in rows.items()
    }
    assert (body[A]["resumed_from"], body[A]["resumed_as"]) == (None, B)
    assert (body[B]["resumed_from"]["parent_execution_id"], body[B]["resumed_as"]) == (A, C)
    assert (body[C]["resumed_from"]["parent_execution_id"], body[C]["resumed_as"]) == (B, None)
