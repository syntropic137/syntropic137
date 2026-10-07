"""#1547: a failed run's quarantined refs reach `GET /executions/{id}` as data.

Real events through the real projection, read out of the HTTP response model,
because a field dropped at any hop between them would leave the refs as prose
in `error_message` only, which is what the issue reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration import QuarantinedRef
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-1547"
_AT = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
_REF = QuarantinedRef(
    repository="acme/widget",
    branch="feat/thing",
    ref=f"refs/syn/lost/{EXECUTION_ID}/implement",
    commit="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    commit_count=2,
    pull_request=42,
)


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


@pytest.mark.asyncio
async def test_the_execution_detail_names_the_ref_and_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    await projection.on_workflow_execution_started(
        WorkflowExecutionStartedEvent(
            workflow_id="wf-1",
            execution_id=EXECUTION_ID,
            workflow_name="wf",
            started_at=_AT,
            total_phases=1,
            inputs={},
        ).model_dump()
    )
    await projection.on_workflow_failed(
        WorkflowFailedEvent(
            workflow_id="wf-1",
            execution_id=EXECUTION_ID,
            failed_at=_AT,
            error_message="phase timed out",
            failed_phase_id="implement",
            completed_phases=0,
            total_phases=1,
            quarantined_refs=[_REF],
        ).model_dump()
    )
    manager = _StubProjectionManager(store=store, workflow_execution_detail=projection)

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    detail = await queries.get_execution_endpoint(EXECUTION_ID)

    assert detail.quarantined_refs == [_REF]
    body = detail.model_dump(mode="json")["quarantined_refs"]
    assert body[0]["ref"] == _REF.ref and body[0]["commit"] == _REF.commit
