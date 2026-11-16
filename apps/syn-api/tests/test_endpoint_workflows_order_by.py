"""`GET /workflows?order_by=` orders the whole collection, not one page (#1843).

The route used to fetch a page in the default newest-first order and then sort
only that page, so the dashboard's "top workflows by runs" showed the newest N
workflows re-sorted rather than the N with the most runs. These tests seed a
real projection and ask over HTTP, so the route, the service and the
projection's order-then-page step are all on the path under test.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.workflows.queries import WorkflowListResponse, router

pytestmark = pytest.mark.unit

PAGE_SIZE = 3

# (name, runs) per template, created oldest first: wf-00 is the oldest, so the
# default newest-first page 1 is wf-06, wf-05, wf-04 and holds neither the
# most-run templates nor the alphabetically first names. wf-00 has 10 runs and
# wf-01 9, which a text sort would put the wrong way round ("10" < "9").
_SEED = [
    ("Echo", 10),
    ("Bravo", 9),
    ("Golf", 2),
    ("Alpha", 0),
    ("Foxtrot", 1),
    ("Charlie", 3),
    ("Delta", 9),
]


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
    from datetime import UTC, datetime

    from event_sourcing import EventEnvelope, EventMetadata

    from syn_api._wiring import get_projection_mgr
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        WorkflowClassification,
        WorkflowType,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
        WorkflowTemplateCreatedEvent,
    )

    mgr = get_projection_mgr()
    for i, (name, runs) in enumerate(_SEED):
        workflow_id = f"wf-{i:02d}"
        await mgr.process_event_envelope(
            EventEnvelope(
                event=WorkflowTemplateCreatedEvent(
                    workflow_id=workflow_id,
                    name=name,
                    workflow_type=WorkflowType.CUSTOM,
                    classification=WorkflowClassification.SIMPLE,
                    repository_url="",
                    repository_ref="main",
                    phases=[],
                ),
                metadata=EventMetadata(
                    aggregate_id=workflow_id,
                    aggregate_type="WorkflowTemplate",
                    aggregate_nonce=1,
                    global_nonce=i + 1,
                    event_type="WorkflowTemplateCreated",
                    recorded_timestamp=datetime(2026, 1, i + 1, tzinfo=UTC),
                ),
            )
        )
        for _ in range(runs):
            await mgr.workflow_list.on_workflow_execution_started({"workflow_id": workflow_id})


async def _walk(order_by: str) -> list[list[str]]:
    """Every page's ids, in order, for one ``order_by``."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    app.include_router(router)
    pages: list[list[str]] = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for page in range(1, len(_SEED) // PAGE_SIZE + 2):
            response = await client.get(
                "/workflows",
                params={"page": page, "page_size": PAGE_SIZE, "order_by": order_by},
            )
            assert response.status_code == 200, response.text
            body = WorkflowListResponse.model_validate_json(response.content)
            assert body.total == len(_SEED)
            pages.append([w.id for w in body.workflows])
    return pages


def _assert_partition(pages: list[list[str]]) -> None:
    flat = [i for page in pages for i in page]
    assert len(flat) == len(set(flat)) == len(_SEED), f"a row was repeated or skipped: {pages}"


async def test_most_runs_first_is_global_and_numeric() -> None:
    """10 before 9, and the 9-run tie broken by id, across page boundaries."""
    await _seed()
    pages = await _walk("-runs_count")
    _assert_partition(pages)
    assert pages == [
        ["wf-00", "wf-01", "wf-06"],
        ["wf-05", "wf-02", "wf-04"],
        ["wf-03"],
    ]


async def test_name_order_is_global() -> None:
    await _seed()
    pages = await _walk("name")
    _assert_partition(pages)
    assert pages == [
        ["wf-03", "wf-01", "wf-05"],
        ["wf-06", "wf-00", "wf-04"],
        ["wf-02"],
    ]


async def test_unknown_field_keeps_the_default_newest_first_order() -> None:
    await _seed()
    pages = await _walk("-no_such_field")
    _assert_partition(pages)
    assert pages[0] == ["wf-06", "wf-05", "wf-04"]
