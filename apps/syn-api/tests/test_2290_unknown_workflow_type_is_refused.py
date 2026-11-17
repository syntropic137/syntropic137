"""An unknown workflow type is a 422, never a silent `custom` (#2290).

Before #2290 the create route mapped anything outside research/planning/
implementation/review/deployment/custom to CUSTOM and answered 201, echoing
the value the caller sent; the YAML install entrance did the same in
`build_command_from_definition`. `analysis`, which a shipped workflow
declared, was stored as something nobody asked for.

Everything goes through the real app: a value is only proven stored when the
list and detail routes read it back.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient, Response

from syn_domain.contexts.orchestration import WorkflowType

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
    body = {"name": "Workflow type #2290", "requires_repos": False, **fields}
    return await client.post("/workflows", json=body)


async def _stored_workflow_type(client: AsyncClient, workflow_id: str) -> tuple[str, str]:
    """The workflow type as the detail and the list routes report it."""
    detail = await client.get(f"/workflows/{workflow_id}")
    assert detail.status_code == 200, detail.text
    listed = await client.get("/workflows")
    assert listed.status_code == 200, listed.text
    [summary] = [w for w in listed.json()["workflows"] if w["id"] == workflow_id]
    return detail.json()["workflow_type"], summary["workflow_type"]


@pytest.mark.parametrize("workflow_type", list(WorkflowType))
async def test_every_workflow_type_round_trips(
    client: AsyncClient, workflow_type: WorkflowType
) -> None:
    response = await _create(client, workflow_type=workflow_type.value)

    assert response.status_code == 201, response.text
    assert response.json()["workflow_type"] == workflow_type.value
    assert await _stored_workflow_type(client, response.json()["id"]) == (
        workflow_type.value,
        workflow_type.value,
    )


@pytest.mark.parametrize("workflow_type", ["analysis", "reserach", ""])
async def test_an_unknown_workflow_type_is_refused_naming_the_choices(
    client: AsyncClient, workflow_type: str
) -> None:
    response = await _create(client, workflow_type=workflow_type)

    assert response.status_code == 422, response.text
    message = response.text
    for allowed in WorkflowType:
        assert allowed.value in message
    listed = await client.get("/workflows")
    assert listed.json()["workflows"] == []


async def test_an_absent_workflow_type_is_custom(client: AsyncClient) -> None:
    response = await _create(client)

    assert response.status_code == 201, response.text
    assert await _stored_workflow_type(client, response.json()["id"]) == ("custom", "custom")


async def test_mixed_case_is_accepted_and_stored_canonically(client: AsyncClient) -> None:
    response = await _create(client, workflow_type="ReViEw")

    assert response.status_code == 201, response.text
    assert response.json()["workflow_type"] == "review"
    assert await _stored_workflow_type(client, response.json()["id"]) == ("review", "review")


async def test_the_service_refuses_too() -> None:
    """`create_workflow` is importable and called directly; it must not default either."""
    from syn_api.routes.workflows import create_workflow
    from syn_api.types import Err, WorkflowError

    result = await create_workflow(name="direct", requires_repos=False, workflow_type="analysis")

    assert isinstance(result, Err)
    assert result.error == WorkflowError.INVALID_INPUT
    assert ", ".join(WorkflowType) in (result.message or "")


# `syn workflow install` and `syn workflow create --from` POST YAML to a
# separate entrance that never sees the JSON request validator.
_YAML = """\
id: yaml-2290
name: YAML workflow type #2290
{workflow_type}
requires_repos: false
phases:
  - id: only
    name: Only
    order: 1
    prompt_template: Say hello.
"""


async def _install(
    client: AsyncClient, workflow_type: str | None, *, force: bool = False
) -> Response:
    line = "" if workflow_type is None else f"type: {workflow_type}"
    return await client.post(
        "/workflows/from-yaml",
        params={"version": "1.0.0", "package_name": "pkg-2290", "force": force},
        content=_YAML.format(workflow_type=line),
        headers={"content-type": "application/yaml"},
    )


@pytest.mark.parametrize("workflow_type", list(WorkflowType))
async def test_every_workflow_type_round_trips_through_yaml_install(
    client: AsyncClient, workflow_type: WorkflowType
) -> None:
    response = await _install(client, workflow_type.value)

    assert response.status_code == 201, response.text
    assert await _stored_workflow_type(client, response.json()["id"]) == (
        workflow_type.value,
        workflow_type.value,
    )


async def test_an_absent_workflow_type_is_custom_through_yaml_install(
    client: AsyncClient,
) -> None:
    response = await _install(client, None)

    assert response.status_code == 201, response.text
    assert await _stored_workflow_type(client, response.json()["id"]) == ("custom", "custom")


@pytest.mark.parametrize("workflow_type", ["analysis", "reserach"])
async def test_yaml_install_refuses_an_unknown_workflow_type_with_422(
    client: AsyncClient, workflow_type: str
) -> None:
    response = await _install(client, workflow_type)

    assert response.status_code == 422, response.text
    for allowed in WorkflowType:
        assert allowed.value in response.text
    listed = await client.get("/workflows")
    assert listed.json()["workflows"] == []


@pytest.mark.parametrize("workflow_type", ["analysis", "reserach"])
async def test_a_refused_reinstall_leaves_the_stored_workflow_type(
    client: AsyncClient, workflow_type: str
) -> None:
    installed = await _install(client, "review")
    assert installed.status_code == 201, installed.text

    response = await _install(client, workflow_type, force=True)

    assert response.status_code == 422, response.text
    assert await _stored_workflow_type(client, installed.json()["id"]) == ("review", "review")


async def test_other_yaml_schema_errors_keep_their_400(client: AsyncClient) -> None:
    response = await client.post(
        "/workflows/from-yaml",
        content="id: yaml-2290\nname: No phases\ntype: research\nphases: nope\n",
        headers={"content-type": "application/yaml"},
    )

    assert response.status_code == 400, response.text


def test_every_shipped_workflow_declares_a_known_type() -> None:
    """Seeding and `syn workflow install` of the repo's own packages must not 422.

    `retrospective-v1` declared `type: analysis` and was stored as custom.
    """
    from pathlib import Path

    import yaml

    repo_root = Path(__file__).resolve().parents[3]
    files = sorted((repo_root / "workflows").rglob("workflow.yaml"))
    assert files
    declared = {path: yaml.safe_load(path.read_text()).get("type") for path in files}
    unknown = {
        str(path.relative_to(repo_root)): workflow_type
        for path, workflow_type in declared.items()
        if workflow_type is not None and workflow_type not in set(WorkflowType)
    }
    assert unknown == {}
