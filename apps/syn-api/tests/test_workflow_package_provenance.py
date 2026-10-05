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


def _app():
    from fastapi import FastAPI

    from syn_api.routes.workflows.commands import router as commands_router
    from syn_api.routes.workflows.queries import router as queries_router

    app = FastAPI()
    app.include_router(commands_router)
    app.include_router(queries_router)
    return app


async def test_package_name_query_string_survives_http_post_to_get() -> None:
    """The hop the service-level tests skip: FastAPI binding the query string."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        posted = await client.post(
            "/workflows/from-yaml",
            params={"version": "3.0.0", "package_name": "implement-v3"},
            content=_YAML.encode(),
            headers={"content-type": "application/yaml"},
        )
        assert posted.status_code == 201, posted.text
        got = await client.get("/workflows/sdlc-implement-v3")
    assert got.status_code == 200, got.text
    assert got.json()["package_name"] == "implement-v3"


async def _is_archived(workflow_id: str) -> bool:
    from syn_api._wiring import get_workflow_repo

    aggregate = await get_workflow_repo().get_by_id(workflow_id)
    assert aggregate is not None
    return aggregate.is_archived


async def test_stale_read_cannot_archive_a_workflow_another_package_now_owns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production's projection lags the aggregate (ADR-055), and the incident's
    first GET was stale. Owner A installs; owner B reinstalls while the read
    model is frozen; GET still says A. A's prune must not archive B's workflow,
    because the archive is checked against the aggregate, not the read."""
    from httpx import ASGITransport, AsyncClient

    from syn_api.routes.workflows import commands

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        first = await client.post(
            "/workflows/from-yaml",
            params={"version": "3.0.0", "package_name": "implement"},
            content=_YAML.encode(),
            headers={"content-type": "application/yaml"},
        )
        assert first.status_code == 201, first.text

        # Freeze the read model, as the coordinator does between catch-ups.
        async def _lagging() -> None:
            return None

        monkeypatch.setattr(commands, "sync_published_events_to_projections", _lagging)

        second = await client.post(
            "/workflows/from-yaml",
            params={"version": "3.0.0", "package_name": "implement-v3", "force": "true"},
            content=_YAML.encode(),
            headers={"content-type": "application/yaml"},
        )
        assert second.status_code == 201, second.text

        stale = await client.get("/workflows/sdlc-implement-v3")
        assert stale.json()["package_name"] == "implement", "precondition: the read is stale"

        refused = await client.delete(
            "/workflows/sdlc-implement-v3", params={"expected_package_name": "implement"}
        )
        assert refused.status_code == 409, refused.text
        assert "package mismatch" in refused.text.lower()
        assert await _is_archived("sdlc-implement-v3") is False

        allowed = await client.delete(
            "/workflows/sdlc-implement-v3", params={"expected_package_name": "implement-v3"}
        )
        assert allowed.status_code == 200, allowed.text
        assert await _is_archived("sdlc-implement-v3") is True
