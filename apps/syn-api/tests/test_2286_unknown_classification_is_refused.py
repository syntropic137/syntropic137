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
from httpx import ASGITransport, AsyncClient, Response

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


async def _create(client: AsyncClient, **fields: object) -> Response:
    body = {"name": "Classification #2286", "requires_repos": False, **fields}
    return await client.post("/workflows", json=body)


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
    response = await _create(client, classification=classification.value)

    assert response.status_code == 201, response.text
    assert response.json()["classification"] == classification.value
    assert await _stored_classification(client, response.json()["id"]) == (
        classification.value,
        classification.value,
    )


@pytest.mark.parametrize("classification", ["advanced", "compelx", ""])
async def test_an_unknown_classification_is_refused_naming_the_choices(
    client: AsyncClient, classification: str
) -> None:
    response = await _create(client, classification=classification)

    assert response.status_code == 422, response.text
    message = response.text
    for allowed in WorkflowClassification:
        assert allowed.value in message
    listed = await client.get("/workflows")
    assert listed.json()["workflows"] == []


async def test_an_absent_classification_is_standard(client: AsyncClient) -> None:
    response = await _create(client)

    assert response.status_code == 201, response.text
    assert await _stored_classification(client, response.json()["id"]) == ("standard", "standard")


async def test_mixed_case_is_accepted_and_stored_canonically(client: AsyncClient) -> None:
    response = await _create(client, classification="EpIc")

    assert response.status_code == 201, response.text
    assert response.json()["classification"] == "epic"
    assert await _stored_classification(client, response.json()["id"]) == ("epic", "epic")


async def test_the_service_refuses_too() -> None:
    """`create_workflow` is importable and called directly; it must not default either."""
    from syn_api.routes.workflows import create_workflow
    from syn_api.types import Err, WorkflowError

    result = await create_workflow(name="direct", requires_repos=False, classification="advanced")

    assert isinstance(result, Err)
    assert result.error == WorkflowError.INVALID_INPUT
    assert "simple, standard, complex, epic" in (result.message or "")


# `syn workflow install` and `syn workflow create --from` POST YAML to a
# separate entrance that never sees the JSON request validator.
_YAML = """\
id: yaml-2286
name: YAML classification #2286
type: research
{classification}
requires_repos: false
phases:
  - id: only
    name: Only
    order: 1
    prompt_template: Say hello.
"""


async def _install(
    client: AsyncClient, classification: str | None, *, force: bool = False
) -> Response:
    line = "" if classification is None else f"classification: {classification}"
    return await client.post(
        "/workflows/from-yaml",
        params={"version": "1.0.0", "package_name": "pkg-2286", "force": force},
        content=_YAML.format(classification=line),
        headers={"content-type": "application/yaml"},
    )


@pytest.mark.parametrize("classification", list(WorkflowClassification))
async def test_every_classification_round_trips_through_yaml_install(
    client: AsyncClient, classification: WorkflowClassification
) -> None:
    response = await _install(client, classification.value)

    assert response.status_code == 201, response.text
    assert await _stored_classification(client, response.json()["id"]) == (
        classification.value,
        classification.value,
    )


async def test_an_absent_classification_is_standard_through_yaml_install(
    client: AsyncClient,
) -> None:
    response = await _install(client, None)

    assert response.status_code == 201, response.text
    assert await _stored_classification(client, response.json()["id"]) == ("standard", "standard")


@pytest.mark.parametrize("classification", ["advanced", "compelx"])
async def test_yaml_install_refuses_an_unknown_classification_with_422(
    client: AsyncClient, classification: str
) -> None:
    response = await _install(client, classification)

    assert response.status_code == 422, response.text
    for allowed in WorkflowClassification:
        assert allowed.value in response.text
    listed = await client.get("/workflows")
    assert listed.json()["workflows"] == []


@pytest.mark.parametrize("classification", ["advanced", "compelx"])
async def test_a_refused_reinstall_leaves_the_stored_classification(
    client: AsyncClient, classification: str
) -> None:
    installed = await _install(client, "complex")
    assert installed.status_code == 201, installed.text

    response = await _install(client, classification, force=True)

    assert response.status_code == 422, response.text
    assert await _stored_classification(client, installed.json()["id"]) == ("complex", "complex")


async def test_other_yaml_schema_errors_keep_their_400(client: AsyncClient) -> None:
    response = await client.post(
        "/workflows/from-yaml",
        content="id: yaml-2286\nname: No phases\nclassification: standard\nphases: nope\n",
        headers={"content-type": "application/yaml"},
    )

    assert response.status_code == 400, response.text
