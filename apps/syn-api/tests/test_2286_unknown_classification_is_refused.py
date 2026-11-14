"""An unknown workflow classification is a 422, never a silent `standard` (#2286).

Before #2286 the create route mapped anything outside simple/standard/complex/
epic to STANDARD and answered 201, echoing the value the caller sent. `advanced`,
which the API docs listed, was stored as something nobody asked for.

Everything goes through the real app: a value is only proven stored when the
list and detail routes read it back.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_domain.contexts.orchestration import WorkflowClassification

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


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
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _create(client: AsyncClient, **fields: object) -> tuple[int, dict[str, object]]:
    body = {"name": "Classification #2286", "requires_repos": False, **fields}
    response = await client.post("/workflows", json=body)
    return response.status_code, response.json()


async def _stored_classification(client: AsyncClient, workflow_id: str) -> tuple[str, str]:
    """The classification as the detail and the list routes report it."""
    detail = await client.get(f"/workflows/{workflow_id}")
    assert detail.status_code == 200, detail.text
    listed = await client.get("/workflows")
    assert listed.status_code == 200, listed.text
    [summary] = [w for w in listed.json()["workflows"] if w["id"] == workflow_id]
    return detail.json()["classification"], summary["classification"]


@pytest.mark.parametrize("classification", list(WorkflowClassification))
async def test_every_classification_round_trips(
    client: AsyncClient, classification: WorkflowClassification
) -> None:
    status, created = await _create(client, classification=classification.value)

    assert status == 201, created
    assert created["classification"] == classification.value
    assert await _stored_classification(client, str(created["id"])) == (
        classification.value,
        classification.value,
    )


@pytest.mark.parametrize("classification", ["advanced", "compelx", ""])
async def test_an_unknown_classification_is_refused_naming_the_choices(
    client: AsyncClient, classification: str
) -> None:
    status, body = await _create(client, classification=classification)

    assert status == 422, body
    message = str(body)
    for allowed in WorkflowClassification:
        assert allowed.value in message
    listed = await client.get("/workflows")
    assert listed.json()["workflows"] == []


async def test_an_absent_classification_is_standard(client: AsyncClient) -> None:
    status, created = await _create(client)

    assert status == 201, created
    assert await _stored_classification(client, str(created["id"])) == ("standard", "standard")


async def test_mixed_case_is_accepted_and_stored_canonically(client: AsyncClient) -> None:
    status, created = await _create(client, classification="EpIc")

    assert status == 201, created
    assert created["classification"] == "epic"
    assert await _stored_classification(client, str(created["id"])) == ("epic", "epic")


async def test_the_service_refuses_too() -> None:
    """`create_workflow` is importable and called directly; it must not default either."""
    from syn_api.routes.workflows import create_workflow
    from syn_api.types import Err, WorkflowError

    result = await create_workflow(name="direct", requires_repos=False, classification="advanced")

    assert isinstance(result, Err)
    assert result.error == WorkflowError.INVALID_INPUT
    assert "simple, standard, complex, epic" in (result.message or "")
