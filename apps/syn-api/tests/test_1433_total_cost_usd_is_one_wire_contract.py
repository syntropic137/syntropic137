"""#1433 part 1: ``total_cost_usd`` has one contract, on executions and sessions.

THE CONTRACT. ``Decimal`` in Python; a JSON string on the wire, because that is
how Pydantic serialises ``Decimal`` and JSON has no exact number type. Three of
the four ``types.py`` models declared ``Decimal | str`` while ``SessionSummary``
declared ``Decimal``. Every producer already hands them a ``Decimal`` (Lane 2's
``ExecutionCost``), so the ``str`` arm was never populated and the wire never
differed; what the union did was tell every reader of the type that it might.

WHAT FAILS WITHOUT THE CHANGE. ``test_every_cost_model_declares_one_string_shape``:
the union declares a two-armed ``anyOf`` serialisation schema. The response
tests are characterisation: they pin the string the clients parse, end to end
from a Lane 2 cost through each endpoint, so narrowing a model can never turn
it into a float or a bare number unnoticed.

``0.11584`` is the issue's own measured value; it is never a default, so a
response carrying it got it from the fixture and nothing else.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from syn_api.types import (
    ExecutionDetail,
    ExecutionDetailFull,
    ExecutionSummary,
    Ok,
    SessionSummary,
)
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostsForIds,
)
from syn_domain.pagination import Page

if TYPE_CHECKING:
    from pydantic import BaseModel

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

COST = "0.11584"
EXEC_ID = "exec-3060768a275b"


@pytest.fixture(autouse=True)
def _reset_storage():
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


async def _seed_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """A list row and a detail row in Lane 1, and the execution's cost in Lane 2."""
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()
    common = {
        "workflow_execution_id": EXEC_ID,
        "workflow_id": "wf-1433",
        "workflow_name": "Cost contract",
        "status": "completed",
        "started_at": "2026-10-18T10:00:00Z",
        "completed_at": "2026-10-18T10:05:00Z",
    }
    await manager.workflow_execution_list._store.save(
        "workflow_executions",
        EXEC_ID,
        {**common, "completed_phases": 1, "total_phases": 1, "total_tokens": 10},
    )
    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        EXEC_ID,
        {**common, "execution_id": EXEC_ID, "phases": [], "artifact_ids": []},
    )
    lane2 = ExecutionCost(
        execution_id=EXEC_ID, total_cost_usd=Decimal(COST), input_tokens=4, output_tokens=6
    )
    monkeypatch.setattr(
        manager.execution_cost,
        "list_costs_for_ids",
        AsyncMock(return_value=ExecutionCostsForIds(costs=[lane2], tool_calls={})),
    )
    monkeypatch.setattr(manager.execution_cost, "get_execution_cost", AsyncMock(return_value=lane2))


async def test_an_execution_summary_holds_the_cost_as_a_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.executions import list_

    await _seed_execution(monkeypatch)

    result = await list_()

    assert isinstance(result, Ok)
    (summary,) = result.value
    assert type(summary.total_cost_usd) is Decimal
    assert summary.total_cost_usd == Decimal(COST)


async def test_the_execution_list_sends_the_cost_as_a_json_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.executions import queries

    await _seed_execution(monkeypatch)

    response = await queries.list_executions_endpoint(
        status=None,
        statuses=None,
        started_after=None,
        started_before=None,
        q=None,
        tag=None,
        eval_id=None,
        in_eval=None,
        page=1,
        page_size=50,
    )

    (row,) = response.model_dump(mode="json")["executions"]
    assert row["total_cost_usd"] == COST


async def test_the_execution_detail_sends_the_cost_as_a_json_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.executions import queries

    await _seed_execution(monkeypatch)

    response = await queries.get_execution_endpoint(EXEC_ID)

    assert response.model_dump(mode="json")["total_cost_usd"] == COST


async def test_the_session_list_sends_the_cost_as_a_json_string() -> None:
    from syn_api.routes import sessions

    page = Page(
        rows=[SessionSummary(id="sess-1433", status="completed")], total=1, status_counts={}
    )
    enrichment = {"sess-1433": sessions._SummaryEnrichment(total_cost_usd=Decimal(COST))}  # pyright: ignore[reportPrivateUsage]
    with (
        patch.object(sessions, "list_sessions", new=AsyncMock(return_value=Ok(page))),
        patch.object(sessions, "_build_workflow_name_map", new=AsyncMock(return_value={})),
        patch.object(sessions, "_load_session_costs", new=AsyncMock(return_value=enrichment)),
    ):
        response = await sessions.list_sessions_endpoint(
            workflow_id=None,
            execution_id=None,
            status=None,
            statuses=None,
            started_after=None,
            started_before=None,
            q=None,
            page=1,
            page_size=50,
            limit=None,
        )

    (row,) = response.model_dump(mode="json")["sessions"]
    assert row["total_cost_usd"] == COST


@pytest.mark.parametrize(
    "model", [ExecutionSummary, ExecutionDetail, ExecutionDetailFull, SessionSummary]
)
def test_every_cost_model_declares_one_string_shape(model: type[BaseModel]) -> None:
    """A union shows up here as ``anyOf``; one contract is one plain string."""
    schema = model.model_json_schema(mode="serialization")["properties"]["total_cost_usd"]

    assert "anyOf" not in schema
    assert schema["type"] == "string"
