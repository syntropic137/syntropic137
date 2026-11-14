"""#975 item 2: a workflow list row carries its classification and description.

The detail served both; the list did not, so an agent choosing a workflow
needed one request per candidate. These install workflows through the real
YAML command, let the real projections build, and read `GET /workflows` and
`GET /workflows/{id}` over HTTP, so a read model that does not keep a field, a
constructor that does not pass it, or a response model that does not declare
it, all fail here.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

# In-memory adapters, as the other service-level workflow tests do.
os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.workflows.commands import create_workflow_from_yaml
from syn_api.types import Ok

pytestmark = pytest.mark.unit


def _yaml(workflow_id: str, classification: str, description: str | None) -> str:
    described = "" if description is None else f'description: "{description}"\n'
    return f"""
id: {workflow_id}
name: {workflow_id}
type: research
classification: {classification}
{described}
phases:
  - id: only
    name: Only
    order: 1
    prompt_template: "Do it."
"""


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


async def _get(path: str) -> dict[str, object]:
    """A response body exactly as a caller receives it."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from syn_api.routes.workflows.queries import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


async def _install(workflow_id: str, classification: str, description: str | None) -> None:
    result = await create_workflow_from_yaml(_yaml(workflow_id, classification, description))
    assert isinstance(result, Ok)


async def _rows() -> dict[object, dict[str, object]]:
    body = await _get("/workflows")
    workflows = body["workflows"]
    assert isinstance(workflows, list)
    return {row["id"]: row for row in workflows}


async def test_a_listed_workflow_carries_what_it_was_created_with() -> None:
    """Non-default values on both, so no model default can be what answers."""
    await _install("triage", "complex", "Sorts incoming issues by area")

    row = (await _rows())["triage"]
    detail = await _get("/workflows/triage")

    assert row["classification"] == "complex"
    assert row["description"] == "Sorts incoming issues by area"
    assert (row["classification"], row["description"]) == (
        detail["classification"],
        detail["description"],
    )


async def test_two_workflows_keep_their_own_values() -> None:
    """A value copied from the wrong row is only visible when rows differ."""
    await _install("one", "epic", "first")
    await _install("two", "simple", "second")

    rows = await _rows()

    assert (rows["one"]["classification"], rows["one"]["description"]) == ("epic", "first")
    assert (rows["two"]["classification"], rows["two"]["description"]) == ("simple", "second")


async def test_no_description_is_listed_as_null() -> None:
    """The key is present and null, matching the detail, not left off the row."""
    await _install("bare", "complex", None)

    row = (await _rows())["bare"]
    detail = await _get("/workflows/bare")

    assert "description" in row
    assert row["description"] is None
    assert detail["description"] is None


def test_constructing_a_row_without_classification_raises() -> None:
    """The domain always has one, so a builder that forgets it must fail (#955 rule)."""
    from syn_api.routes.workflows.queries import WorkflowSummaryResponse

    with pytest.raises(ValidationError, match="classification"):
        WorkflowSummaryResponse(
            id="wf-1",
            name="wf",
            workflow_type="custom",
            description=None,
            phase_count=1,
            requires_repos=False,
        )
