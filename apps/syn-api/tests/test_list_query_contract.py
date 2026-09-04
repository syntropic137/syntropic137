"""The list endpoints must answer about the collection the request asked for (#1159, #1160).

`GET /executions` computed its rows by filtering in Python and its `total` by
issuing a store-level `COUNT(*)`. The two spelled the same predicate twice and
agreed only for as long as the predicate stayed one equality check. Adding a
time window to the rows would have left `total` counting all of history, so a
24-hour view reported a number that belongs to a different collection - and
`total` is the only field a client can page against.

`GET /sessions` had the opposite defect: its window was applied correctly and
server-side, but there was no `page` or `offset` at all and the cap was 200, so
roughly a day of history was reachable and the rest was not addressable at any
parameter setting.

These tests drive the routes over ASGI rather than calling the endpoint
functions, because the failure mode is a QUERY PARAMETER that never arrives.
FastAPI ignores unknown query parameters by default, so a server that does not
declare `started_after` accepts the request, drops the bound, and returns a
confident answer about the wrong set. Calling the endpoint function directly
cannot see that: an undeclared parameter is a `TypeError` in Python and a
silent success over HTTP, and only one of those is what a client experiences.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import pytest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping

#: Everything these tests put in a query string.
type QueryValue = str | int


class _Seeder(Protocol):
    """Seeds one row into a list projection. Both list surfaces take this shape."""

    def __call__(
        self, row_id: str, *, status: str = ..., started_at: str | None
    ) -> Awaitable[None]: ...


os.environ.setdefault("APP_ENVIRONMENT", "test")

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the gate
# goes green having run none of them (#1065).
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


# -- Seeding ------------------------------------------------------------------

_NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)


def _at(hours_ago: float) -> str:
    return (_NOW - timedelta(hours=hours_ago)).isoformat()


async def _seed_execution(
    row_id: str,
    *,
    status: str = "completed",
    started_at: str | None,
    workflow_id: str = "wf-1",
    workflow_name: str = "Workflow One",
) -> None:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()
    await manager.workflow_execution_list._store.save(
        "workflow_executions",
        row_id,
        {
            "workflow_execution_id": row_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "status": status,
            "started_at": started_at,
            "completed_at": None,
            "completed_phases": 1,
            "total_phases": 1,
            "total_tokens": 0,
            "tool_call_count": 0,
            "error_message": None,
        },
    )


async def _seed_session(
    row_id: str,
    *,
    status: str = "completed",
    started_at: str | None,
    workflow_id: str = "wf-1",
) -> None:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()
    await manager.session_list._store.save(
        "session_summaries",
        row_id,
        {
            "id": row_id,
            "workflow_id": workflow_id,
            "agent_type": "claude",
            "status": status,
            "started_at": started_at,
            "completed_at": None,
            "total_tokens": 0,
        },
    )


# -- HTTP ---------------------------------------------------------------------


async def _get(router_module: str, path: str, **params: QueryValue) -> Mapping[str, Any]:
    """Issue a real GET and return the parsed body.

    Routed through FastAPI so an undeclared query parameter behaves the way it
    does for a client - dropped, not raised.
    """
    import importlib

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    router = importlib.import_module(router_module).router
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, params=params)

    assert response.status_code == 200, response.text
    body: Mapping[str, Any] = response.json()
    return body


async def _executions(**params: QueryValue) -> Mapping[str, Any]:
    return await _get("syn_api.routes.executions.queries", "/executions", **params)


async def _sessions(**params: QueryValue) -> Mapping[str, Any]:
    return await _get("syn_api.routes.sessions", "/sessions", **params)


# -- V1: the window is not a superset of the page -----------------------------


async def test_executions_total_counts_the_window_not_all_of_history():
    """`total` must describe the same collection the rows were cut from.

    120 executions exist; 60 of them started inside the last 24 hours. A client
    asking for the first 50 of that window is told there are 60 - the number it
    has to page against. Reported as 120 it would page into an emptiness that
    the server insists is there, which is the owner's symptom.

    Neither number can arise by accident: 60 is not the collection size, not the
    page size, and not the page length.
    """
    for i in range(60):
        await _seed_execution(f"recent-{i:03d}", started_at=_at(1 + i * 0.1))
    for i in range(60):
        await _seed_execution(f"old-{i:03d}", started_at=_at(48 + i))

    body = await _executions(page_size=50, started_after=_at(24))

    assert body["total"] == 60, (
        "total must count the executions inside the window. 120 means the bound "
        "never reached the count - FastAPI drops query parameters a route does "
        "not declare, so a server that ignores started_after looks like success"
    )
    assert len(body["executions"]) == 50
    returned = {e["workflow_execution_id"] for e in body["executions"]}
    assert all(e.startswith("recent-") for e in returned), (
        "every row on the page must be inside the window, not the newest 50 overall"
    )


async def test_executions_page_two_reaches_the_rest_of_the_window():
    """The remaining 10 of those 60 are reachable, and are different rows."""
    for i in range(60):
        await _seed_execution(f"recent-{i:03d}", started_at=_at(1 + i * 0.1))
    for i in range(60):
        await _seed_execution(f"old-{i:03d}", started_at=_at(48 + i))

    first = await _executions(page_size=50, page=1, started_after=_at(24))
    second = await _executions(page_size=50, page=2, started_after=_at(24))

    ids_1 = {e["workflow_execution_id"] for e in first["executions"]}
    ids_2 = {e["workflow_execution_id"] for e in second["executions"]}
    assert len(ids_2) == 10
    assert not (ids_1 & ids_2)
    assert second["total"] == 60
    assert ids_1 | ids_2 == {f"recent-{i:03d}" for i in range(60)}


# -- V2: page 2 of sessions is not page 1 -------------------------------------


async def test_sessions_page_two_is_a_different_page():
    """`page` must select rows, not be accepted and discarded.

    Distinguishes "paging exists" from "paging is a parameter the server takes
    and ignores", which is what a client saw before: `page` was undeclared, so
    every page was page one and `total` was the page length.
    """
    for i in range(250):
        await _seed_session(f"s-{i:03d}", started_at=_at(i * 0.1))

    first = await _sessions(page_size=50, page=1)
    second = await _sessions(page_size=50, page=2)

    ids_1 = {s["id"] for s in first["sessions"]}
    ids_2 = {s["id"] for s in second["sessions"]}
    assert len(ids_1) == 50
    assert len(ids_2) == 50
    assert not (ids_1 & ids_2), "page 2 returned page 1"
    assert first["total"] == 250
    assert second["total"] == 250


async def test_sessions_paging_reaches_the_oldest_row():
    """The rows past the old 200-row ceiling are addressable at all."""
    for i in range(250):
        await _seed_session(f"s-{i:03d}", started_at=_at(i * 0.1))

    last = await _sessions(page_size=50, page=5)
    ids = {s["id"] for s in last["sessions"]}
    assert "s-249" in ids, (
        "the oldest session was unreachable at any parameter setting: no page "
        "or offset existed and the cap was 200"
    )


# -- V4: `limit` still works and `page_size` wins -----------------------------


async def test_sessions_limit_is_a_deprecated_alias_that_page_size_overrides():
    """`limit` keeps working for the published CLI flag; `page_size` wins.

    The precedence is only expressible because `limit` no longer defaults to
    50: with a concrete default the endpoint cannot tell "omitted" from
    "explicitly 50" and has nothing to apply the rule to.
    """
    for i in range(120):
        await _seed_session(f"s-{i:03d}", started_at=_at(i * 0.1))

    alias_only = await _sessions(limit=10)
    assert len(alias_only["sessions"]) == 10
    assert alias_only["page_size"] == 10

    both = await _sessions(limit=10, page_size=25)
    assert len(both["sessions"]) == 25, "page_size must win over limit"
    assert both["page_size"] == 25

    neither = await _sessions()
    assert len(neither["sessions"]) == 50
    assert neither["page_size"] == 50, (
        "omitting both must still mean 50 - changing limit's default from 50 "
        "to None must not change what a caller passing nothing receives"
    )


# -- V5: a null started_at row behaves identically in rows, total and counts ---


async def test_a_session_with_no_start_time_is_absent_from_all_three_under_a_window():
    """A row the query excludes must not be counted by the numbers beside it.

    A count that includes rows the query drops is the #920 class of bug: the
    caller is told to page towards something that is not there.
    """
    await _seed_session("started", status="completed", started_at=_at(1))
    await _seed_session("never-started", status="pending", started_at=None)

    windowed = await _sessions(started_after=_at(24))
    assert [s["id"] for s in windowed["sessions"]] == ["started"]
    assert windowed["total"] == 1
    assert windowed["status_counts"] == {"completed": 1}

    unwindowed = await _sessions()
    assert {s["id"] for s in unwindowed["sessions"]} == {"started", "never-started"}
    assert unwindowed["total"] == 2
    assert unwindowed["status_counts"] == {"completed": 1, "pending": 1}


# -- V8: status_counts is status-neutral and time/search-aware ----------------

_FACET_DISTRIBUTION = [("completed", 7), ("failed", 3), ("running", 2)]


async def _seed_facet_fixture(seed: _Seeder, prefix: str) -> None:
    """7 completed / 3 failed / 2 running inside the window, plus 5 outside it."""
    n = 0
    for status, howmany in _FACET_DISTRIBUTION:
        for _ in range(howmany):
            await seed(f"{prefix}-in-{n:02d}", status=status, started_at=_at(1))
            n += 1
    for i in range(5):
        await seed(f"{prefix}-out-{i}", status="completed", started_at=_at(72))


async def test_execution_status_counts_ignore_the_status_filter_but_not_the_window():
    """Chips say what selecting a different status WOULD return.

    Tallied after the status filter, every unselected chip reads 0; tallied over
    everything, the chips describe history rather than the window on screen.
    Neither is the number an operator is reading. `failed` is the selection here
    and `completed: 7` is the assertion that survives it.
    """
    await _seed_facet_fixture(_seed_execution, "e")

    body = await _executions(started_after=_at(24), statuses="failed")

    assert body["total"] == 3
    assert len(body["executions"]) == 3
    assert body["status_counts"] == {"completed": 7, "failed": 3, "running": 2}, (
        "the facets must be counted over every filter EXCEPT status: 12 in the "
        "window, and the 5 outside it excluded"
    )


async def test_session_status_counts_ignore_the_status_filter_but_not_the_window():
    await _seed_facet_fixture(_seed_session, "s")

    body = await _sessions(started_after=_at(24), statuses="failed")

    assert body["total"] == 3
    assert len(body["sessions"]) == 3
    assert body["status_counts"] == {"completed": 7, "failed": 3, "running": 2}


async def test_execution_search_narrows_the_rows_the_total_and_the_facets_together():
    """Search has to happen where `total` is computed.

    Applied on the client instead - which is where it lived - the row count and
    the pagination label describe different sets the moment the box is
    non-empty. 4 here is a number no unsearched query returns.
    """
    for i in range(4):
        await _seed_execution(
            f"needle-{i}", status="completed", started_at=_at(1), workflow_name="Nightly Audit"
        )
    for i in range(8):
        await _seed_execution(
            f"other-{i}", status="failed", started_at=_at(1), workflow_name="Something Else"
        )

    body = await _executions(started_after=_at(24), q="nightly")

    assert body["total"] == 4
    assert len(body["executions"]) == 4
    assert sum(body["status_counts"].values()) == 4, (
        "the facets must be counted over the search too, or the chips add up to "
        "a different collection than the rows"
    )
    assert body["status_counts"] == {"completed": 4}


async def test_session_search_matches_the_session_id_case_insensitively():
    await _seed_session("AlphaOne", status="completed", started_at=_at(1))
    await _seed_session("BetaTwo", status="running", started_at=_at(1))

    body = await _sessions(q="alpha")

    assert [s["id"] for s in body["sessions"]] == ["AlphaOne"]
    assert body["total"] == 1
    assert body["status_counts"] == {"completed": 1}
