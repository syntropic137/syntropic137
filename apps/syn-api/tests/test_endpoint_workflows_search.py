"""`GET /workflows?search=` searches the whole collection, not one page.

The dashboard filtered the page it had already fetched, so a workflow on page 3
could never be found from page 1. The fix moves the match into the query,
ahead of pagination; these tests pin that by seeding a real projection and
asking over HTTP, so the route's parameter declaration, the service and the
projection's filter-then-page order are all on the path under test.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.workflows.queries import WorkflowListResponse, router

pytestmark = pytest.mark.unit

PAGE_SIZE = 5
TOTAL = 15


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
    yield
    reset_storage()
    reset_projection_manager()


async def _seed() -> None:
    """15 templates, newest first, so `wf-00` lands last: on page 3 of 5-row pages."""
    from syn_api._wiring import get_projection_mgr

    projection = get_projection_mgr().workflow_list
    for i in range(TOTAL):
        name = "Needle Release Train" if i == 0 else f"Workflow {i:02d}"
        await projection.on_workflow_template_created(
            {
                "workflow_id": f"wf-{i:02d}",
                "name": name,
                "workflow_type": "custom",
                "created_at": f"2026-01-{i + 1:02d}T00:00:00+00:00",
            }
        )


async def _get(**params: str | int) -> WorkflowListResponse:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/workflows", params={"page_size": PAGE_SIZE, **params})
    assert response.status_code == 200, response.text
    return WorkflowListResponse.model_validate_json(response.content)


def _ids(body: WorkflowListResponse) -> list[str]:
    return [w.id for w in body.workflows]


async def test_the_needle_starts_on_page_three() -> None:
    """Precondition: without search, the target is not on page 1."""
    await _seed()
    assert "wf-00" not in _ids(await _get(page=1))
    assert "wf-00" in _ids(await _get(page=3))


async def test_search_from_page_one_finds_a_workflow_on_page_three() -> None:
    await _seed()
    body = await _get(page=1, search="nEeDlE")
    assert _ids(body) == ["wf-00"]
    assert body.total == 1
    assert body.page == 1


async def test_search_matches_id_and_total_is_the_filtered_count() -> None:
    """`wf-1` matches wf-10..wf-14: five rows, so `total` is 5, not 15."""
    await _seed()
    body = await _get(page=1, search="WF-1")
    assert sorted(_ids(body)) == ["wf-10", "wf-11", "wf-12", "wf-13", "wf-14"]
    assert body.total == 5


async def test_search_pages_over_the_filtered_set() -> None:
    """`workflow` matches the 14 non-needle names: page 3 holds the last 4."""
    await _seed()
    body = await _get(page=3, search="workflow")
    assert body.total == TOTAL - 1
    assert len(_ids(body)) == TOTAL - 1 - 2 * PAGE_SIZE


async def test_unknown_search_returns_nothing() -> None:
    await _seed()
    body = await _get(page=1, search="no-such-workflow")
    assert _ids(body) == []
    assert body.total == 0
