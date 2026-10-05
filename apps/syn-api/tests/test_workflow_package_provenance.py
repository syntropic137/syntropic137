"""The installing package is recorded and read back on GET (#1588).

`syn workflow install --prune` archives a workflow only when the server says
the package being installed is the one that installed it. That answer is only
as good as the hop that carries it: query string -> command -> event ->
aggregate fingerprint -> workflow_detail projection -> response JSON. These
tests drive both ends of that chain - the install entry point and the
serialized GET body the CLI reads - so a field dropped at any hop between
them fails here.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.workflows.commands import create_workflow_from_yaml
from syn_api.types import Ok

pytestmark = pytest.mark.unit


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


async def _get_package_name(workflow_id: str) -> tuple[bool, object]:
    """(key present, value) for ``package_name`` in the serialized GET body."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from syn_api.routes.workflows.queries import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/workflows/{workflow_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    return "package_name" in body, body.get("package_name")


_YAML = """
id: sdlc-implement-v3
name: SDLC Implement v3
type: implementation
classification: standard
phases:
  - id: build
    name: Build
    order: 1
    prompt_template: "Build it."
"""


async def test_installing_package_is_read_back_on_get() -> None:
    result = await create_workflow_from_yaml(_YAML, version="3.0.0", package_name="implement-v3")
    assert isinstance(result, Ok)

    assert await _get_package_name("sdlc-implement-v3") == (True, "implement-v3")


async def test_a_workflow_not_installed_from_a_package_reports_none() -> None:
    assert isinstance(await create_workflow_from_yaml(_YAML), Ok)

    assert await _get_package_name("sdlc-implement-v3") == (True, None)


async def test_reinstall_under_another_package_is_a_change_not_a_no_op() -> None:
    """Only package_name differs. If the aggregate's fingerprint ignored it,
    the reinstall would be reported "unchanged", write no event, and the
    server would keep naming the old package as owner."""
    first = await create_workflow_from_yaml(_YAML, version="3.0.0", package_name="implement")
    assert isinstance(first, Ok)

    second = await create_workflow_from_yaml(
        _YAML, version="3.0.0", package_name="implement-v3", force=True
    )
    assert isinstance(second, Ok)
    assert second.value.changed is True

    assert await _get_package_name("sdlc-implement-v3") == (True, "implement-v3")
