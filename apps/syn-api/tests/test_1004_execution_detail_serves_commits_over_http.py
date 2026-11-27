"""#1004 slice 1: `GET /executions/{id}` serves the commits a run recorded.

Driven from the events, through the projection, into the store the route
reads, so every hop between the recorded event and the JSON is on the path:
the projection, the read model, `ExecutionDetailFull`, and the response. A run
that recorded none serves null, never an empty list.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_api.routes.executions.models import ExecutionDetailResponse
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
    WorkspaceProvisionedForPhaseEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

REPO = "acme/api"
START, CHECKED_OUT = "a" * 40, "b" * 40


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from syn_api._wiring import ensure_connected
    from syn_api.main import create_app

    await ensure_connected()
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _project(execution_id: str, *, recorded: bool) -> None:
    from syn_api._wiring import get_projection_mgr

    projection = WorkflowExecutionDetailProjection(get_projection_mgr().store)
    ids = {"execution_id": execution_id, "workflow_id": "wf", "workflow_name": "wf"}
    await projection.on_workflow_execution_started(
        {**ids, "source_commits": [{"repository": REPO, "sha": START}]} if recorded else ids
    )
    await projection.on_phase_started(
        {"execution_id": execution_id, "phase_id": "p1", "phase_name": "p1"}
    )
    await projection.on_workspace_provisioned_for_phase(
        WorkspaceProvisionedForPhaseEvent(
            workflow_id="wf",
            execution_id=execution_id,
            phase_id="p1",
            workspace_id="ws-1",
            session_id="s-1",
            provisioned_at=datetime(2026, 11, 26, tzinfo=UTC),
            checked_out_commits=[SourceCommit(repository=REPO, sha=CHECKED_OUT)]
            if recorded
            else None,
        )
    )


async def test_the_detail_serves_the_run_and_phase_commits(client: AsyncClient) -> None:
    await _project("exec-commits", recorded=True)

    response = await client.get("/executions/exec-commits")

    assert response.status_code == 200, response.text
    body = ExecutionDetailResponse.model_validate(response.json())
    assert body.source_commits == [SourceCommit(repository=REPO, sha=START)]
    assert body.phases[0].checked_out_commits == [SourceCommit(repository=REPO, sha=CHECKED_OUT)]


async def test_an_older_run_serves_null_not_an_empty_list(client: AsyncClient) -> None:
    await _project("exec-older", recorded=False)

    response = await client.get("/executions/exec-older")

    assert response.status_code == 200, response.text
    raw = response.json()
    # On the wire: the key is present and null, which is "not recorded".
    assert raw["source_commits"] is None
    assert raw["phases"][0]["checked_out_commits"] is None


async def test_a_failed_phase_still_serves_its_checkout(client: AsyncClient) -> None:
    from syn_api._wiring import get_projection_mgr

    await _project("exec-failed", recorded=True)
    await WorkflowExecutionDetailProjection(get_projection_mgr().store).on_workflow_failed(
        {
            "execution_id": "exec-failed",
            "failed_phase_id": "p1",
            "error_message": "boom",
            "failed_at": "2026-11-26T01:00:00+00:00",
        }
    )

    response = await client.get("/executions/exec-failed")

    assert response.status_code == 200, response.text
    body = ExecutionDetailResponse.model_validate(response.json())
    assert body.phases[0].status == "failed"
    assert body.phases[0].checked_out_commits == [SourceCommit(repository=REPO, sha=CHECKED_OUT)]
    assert body.source_commits == [SourceCommit(repository=REPO, sha=START)]
