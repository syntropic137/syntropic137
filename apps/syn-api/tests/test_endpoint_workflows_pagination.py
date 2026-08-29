"""Pagination contract for `GET /api/v1/workflows`.

Reproduces a failure measured against the live Mac Mini deployment, where 32
workflows were registered but the endpoint answered:

    (default page_size=20)   n=20  total=20   <- total described the PAGE
    ?page=2&page_size=20     n=0   total=12   <- page 2 returned NOTHING

Two defects: `total` was `len(summaries)` (the page), and the already-paginated
result was sliced a second time by the same offset. An agent that pages until it
has collected `total` items stopped after page 1 and never saw the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.routes.workflows.queries import list_workflows_endpoint
from syn_api.types import Ok

pytestmark = pytest.mark.unit

TOTAL_WORKFLOWS = 32
PAGE_SIZE = 20


@dataclass
class _Summary:
    id: str
    name: str
    workflow_type: str = "custom"
    classification: str | None = None
    phase_count: int = 1
    description: str | None = None
    created_at: str | None = None
    runs_count: int = 0
    is_archived: bool = False
    requires_repos: bool = False


_ALL = [_Summary(id=f"wf-{i:02d}", name=f"Workflow {i:02d}") for i in range(TOTAL_WORKFLOWS)]


def _page(limit: int, offset: int) -> list[_Summary]:
    """Stand in for the projection: it already applies limit/offset."""
    return _ALL[offset : offset + limit]


async def _call(page: int, page_size: int = PAGE_SIZE):
    """Invoke the endpoint with the projection layer faked out."""

    async def fake_list_workflows(*, workflow_type, limit, offset, include_archived):
        return Ok(_page(limit, offset))

    mgr = MagicMock()
    mgr.workflow_list.count = AsyncMock(return_value=TOTAL_WORKFLOWS)

    with (
        patch(
            "syn_api.routes.workflows.queries.list_workflows",
            new=AsyncMock(side_effect=fake_list_workflows),
        ),
        patch("syn_api.routes.workflows.queries.get_projection_mgr", return_value=mgr),
    ):
        # Every parameter is passed explicitly: calling the function directly
        # bypasses FastAPI, so an omitted arg would arrive as a `Query` object.
        return await list_workflows_endpoint(
            workflow_type=None,
            include_archived=False,
            page=page,
            page_size=page_size,
            order_by=None,
        )


async def test_total_is_the_collection_not_the_page() -> None:
    """`total` must let a caller know more pages exist."""
    resp = await _call(page=1)
    assert len(resp.workflows) == PAGE_SIZE
    assert resp.total == TOTAL_WORKFLOWS, (
        "total described the page, so a client paging until it had `total` items stopped early"
    )


async def test_second_page_returns_the_remainder() -> None:
    """The bug: the already-paginated page was sliced again by the same offset."""
    resp = await _call(page=2)
    assert len(resp.workflows) == TOTAL_WORKFLOWS - PAGE_SIZE
    assert [w.id for w in resp.workflows] == [s.id for s in _ALL[PAGE_SIZE:]]


async def test_pages_partition_the_collection_without_gaps_or_repeats() -> None:
    """Walking every page must yield each workflow exactly once."""
    seen: list[str] = []
    for page in (1, 2):
        resp = await _call(page=page)
        seen.extend(w.id for w in resp.workflows)
    assert seen == [s.id for s in _ALL]
    assert len(set(seen)) == TOTAL_WORKFLOWS


async def test_page_beyond_the_end_is_empty_but_total_still_reported() -> None:
    resp = await _call(page=3)
    assert resp.workflows == []
    assert resp.total == TOTAL_WORKFLOWS
