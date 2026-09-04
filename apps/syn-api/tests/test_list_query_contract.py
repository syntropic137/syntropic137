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
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

import pytest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from httpx import Response

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


async def _request(router_module: str, path: str, **params: QueryValue) -> Response:
    """Issue a real GET and return the response, whatever its status.

    Routed through FastAPI so an undeclared query parameter behaves the way it
    does for a client - dropped, not raised - and so a REJECTED one is the
    status a client sees rather than an exception raised inside the test.
    """
    import importlib

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    router = importlib.import_module(router_module).router
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, params=params)


async def _get(router_module: str, path: str, **params: QueryValue) -> Mapping[str, Any]:
    """The parsed body of a request expected to succeed."""
    response = await _request(router_module, path, **params)
    assert response.status_code == 200, response.text
    body: Mapping[str, Any] = response.json()
    return body


async def _executions(**params: QueryValue) -> Mapping[str, Any]:
    return await _get("syn_api.routes.executions.queries", "/executions", **params)


async def _sessions(**params: QueryValue) -> Mapping[str, Any]:
    return await _get("syn_api.routes.sessions", "/sessions", **params)


async def _executions_response(**params: QueryValue) -> Response:
    return await _request("syn_api.routes.executions.queries", "/executions", **params)


async def _sessions_response(**params: QueryValue) -> Response:
    return await _request("syn_api.routes.sessions", "/sessions", **params)


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


# -- A bound with no timezone is refused, not guessed at and not a 500 (#1183) -
#
# Both endpoints declared `started_after` / `started_before` as a bare
# `datetime`, and FastAPI parses `?started_after=2026-09-01T00:00:00` - and a
# bare `2026-09-01` - into a NAIVE one without complaint. Rows carry aware UTC
# timestamps, Python raises `TypeError` comparing the two, and the endpoint
# answered 500. Live on v0.28.0-beta.7.
#
# The contract chosen is 422, because the server does not know what the value
# MEANS: local midnight in PST and midnight UTC are written identically, and
# reading it as UTC shifts the first by eight hours and returns a confidently
# wrong page. The status is asserted alongside the rows the aware spelling
# returns, so "refuses everything" fails as loudly as "crashes".
#
# Rows are the opposite case and are tested here too: a stored timestamp
# missing its offset is normalised to UTC rather than refused, because there is
# nobody to refuse it TO. That half never appears in a query string, so no
# amount of input validation reaches it - an aware bound (all the dashboard
# ever sends) against a naive row is the same TypeError from the other side.


class _Surface(NamedTuple):
    """One list endpoint, addressed the way these tests need to address it."""

    seed: _Seeder
    get: Callable[..., Awaitable[Mapping[str, Any]]]
    respond: Callable[..., Awaitable[Response]]
    rows_key: str
    id_key: str


_SURFACES = {
    "executions": _Surface(
        _seed_execution, _executions, _executions_response, "executions", "workflow_execution_id"
    ),
    "sessions": _Surface(_seed_session, _sessions, _sessions_response, "sessions", "id"),
}

#: `_NOW - 24h` with no offset, exactly as a hand-edited URL carries it.
_NAIVE_BOUND = "2026-03-31T12:00:00"

#: The same wall-clock reading, spelled the way a generated client sends it.
_AWARE_BOUND = "2026-03-31T12:00:00+00:00"


def _ids(body: Mapping[str, Any], surface: _Surface) -> set[str]:
    return {row[surface.id_key] for row in body[surface.rows_key]}


def _rejection(response: Response) -> str:
    """The one validation error, as `"<field>: <message>"`."""
    assert response.status_code == 422, f"expected a refusal, got {response.status_code}"
    detail = response.json()["detail"]
    assert len(detail) == 1, detail
    return f"{detail[0]['loc'][-1]}: {detail[0]['msg']}"


async def _seed_across_the_bound(surface: _Surface) -> None:
    """3 rows after the bound, 2 before it, all stamped aware UTC.

    Rows on both sides so that a bound which is dropped, or widened to cover
    everything, gives a different answer from one that is honoured.
    """
    for i in range(3):
        await surface.seed(f"after-{i}", started_at=_at(1 + i))
    for i in range(2):
        await surface.seed(f"before-{i}", started_at=_at(30 + i))


@pytest.mark.parametrize("name", list(_SURFACES))
async def test_a_timezone_less_started_after_is_refused_and_says_why(name: str):
    """(a) A naive lower bound against aware rows: 422, and never 500.

    Parametrised over both surfaces because they share one comparator, so the
    contract is not "each endpoint copes" but "the same value means the same
    thing on either". The message has to name the parameter and the fix: a
    bare 422 leaves an operator with a URL they cannot repair.
    """
    surface = _SURFACES[name]
    await _seed_across_the_bound(surface)

    rejection = _rejection(await surface.respond(started_after=_NAIVE_BOUND))

    assert rejection.startswith("started_after: ")
    assert "timezone" in rejection
    assert "2026-09-01T00:00:00Z" in rejection, (
        "the message must show a value that WOULD work, not just refuse this one"
    )


@pytest.mark.parametrize("name", list(_SURFACES))
async def test_b_timezone_less_started_before_is_refused_the_same_way(name: str):
    """(b) The upper bound is the same parameter twice over, not a second rule."""
    surface = _SURFACES[name]
    await _seed_across_the_bound(surface)

    rejection = _rejection(await surface.respond(started_before=_NAIVE_BOUND))

    assert rejection.startswith("started_before: ")
    assert "timezone" in rejection


@pytest.mark.parametrize("name", list(_SURFACES))
async def test_b_one_naive_bound_is_refused_even_beside_an_aware_one(name: str):
    """(b) Both parameters together: an aware sibling does not excuse the other.

    The pair is where a per-parameter check most easily goes wrong - validating
    whichever arrives first, or only the one the endpoint reads first.
    """
    surface = _SURFACES[name]
    await _seed_across_the_bound(surface)

    assert _rejection(
        await surface.respond(started_after=_NAIVE_BOUND, started_before=_AWARE_BOUND)
    ).startswith("started_after: ")
    assert _rejection(
        await surface.respond(started_after=_AWARE_BOUND, started_before=_NAIVE_BOUND)
    ).startswith("started_before: ")


@pytest.mark.parametrize("name", list(_SURFACES))
async def test_a_bare_date_is_refused_rather_than_crashing(name: str):
    """(a) `2026-03-31` is the shape a human types by hand, and it has no offset.

    It reached the comparator as a naive midnight and 500ed like the rest.
    """
    surface = _SURFACES[name]
    await _seed_across_the_bound(surface)

    assert "timezone" in _rejection(await surface.respond(started_after="2026-03-31"))


@pytest.mark.parametrize("name", list(_SURFACES))
async def test_d_aware_bounds_still_answer_and_still_filter(name: str):
    """(d) The refusal is about the missing offset and nothing else.

    Every offset the server accepted before is still accepted - including a
    non-UTC one, which is the case a "must be Zulu" over-correction breaks -
    and each still selects the same rows. Without this, refusing every bound
    passes each test above.
    """
    surface = _SURFACES[name]
    await _seed_across_the_bound(surface)

    for spelling in (_AWARE_BOUND, "2026-03-31T12:00:00Z", "2026-03-31T14:00:00+02:00"):
        body = await surface.get(started_after=spelling)
        assert _ids(body, surface) == {"after-0", "after-1", "after-2"}, spelling
        assert body["total"] == 3, spelling
        assert body["status_counts"] == {"completed": 3}, spelling

    upper = await surface.get(started_before=_AWARE_BOUND)
    assert _ids(upper, surface) == {"before-0", "before-1"}
    assert upper["total"] == 2


@pytest.mark.parametrize("name", list(_SURFACES))
async def test_d_a_row_with_no_start_time_is_still_outside_a_bounded_window(name: str):
    """(d) The #920 rule the normalisation runs through, unchanged.

    A row that cannot be placed in time stays out of the rows, the total and
    the facets alike - all three, or the count describes rows the query does
    not return.
    """
    surface = _SURFACES[name]
    await _seed_across_the_bound(surface)
    await surface.seed("no-start", status="pending", started_at=None)

    bounded = await surface.get(started_after=_AWARE_BOUND)
    assert "no-start" not in _ids(bounded, surface)
    assert bounded["total"] == 3
    assert bounded["status_counts"] == {"completed": 3}

    unbounded = await surface.get()
    assert "no-start" in _ids(unbounded, surface)
    assert unbounded["total"] == 6


@pytest.mark.parametrize("name", list(_SURFACES))
async def test_an_aware_bound_against_a_row_that_carries_no_offset(name: str):
    """The half of the mismatch that no query parameter can guard.

    A row's `started_at` is whatever its event carried and nothing checks it
    for an offset, so the identical TypeError is reachable from the DATA side -
    and from the aware bounds the dashboard is already sending. Refusing input
    would have left this path 500ing on a request that looks entirely correct,
    which is the worse half for being unreachable from the client that hits it.

    Read as UTC, the naive row sits with its aware twin an hour inside the
    window and the older naive row stays out: the value is placed, not merely
    survived.
    """
    surface = _SURFACES[name]
    await surface.seed("naive-row", started_at="2026-04-01T11:00:00")
    await surface.seed("aware-row", started_at=_at(1))
    await surface.seed("old-naive-row", started_at="2026-03-30T11:00:00")

    body = await surface.get(started_after=_AWARE_BOUND)

    assert _ids(body, surface) == {"naive-row", "aware-row"}
    assert body["total"] == 2


@pytest.mark.parametrize("name", list(_SURFACES))
async def test_a_naive_row_on_the_bound_is_read_as_utc_not_as_local_time(name: str):
    """The row contract pinned to the instant, not to "it did not crash".

    The row is the naive spelling of the bound itself. Read as UTC it sits
    exactly on an inclusive bound and both directions return it; read as local
    time, or converted with `astimezone` on a host that is not UTC, it lands on
    one side and the two queries disagree.
    """
    surface = _SURFACES[name]
    await surface.seed("on-the-bound", started_at="2026-04-01T09:00:00")
    await surface.seed("elsewhere", started_at=_at(30))

    at_lower = await surface.get(started_after="2026-04-01T09:00:00+00:00")
    at_upper = await surface.get(started_before="2026-04-01T09:00:00+00:00")

    assert _ids(at_lower, surface) == {"on-the-bound"}
    assert _ids(at_upper, surface) == {"on-the-bound", "elsewhere"}


async def test_the_reported_reproduction_against_rows_the_real_producer_wrote():
    """The issue's own repro, end to end from the event that writes the row.

    The seeding helpers above write the projection's store directly, so they
    could in principle agree with this test and disagree with production. This
    one goes through `on_workflow_execution_started`, which is what stamps the
    aware timestamps the naive bound was crashing against - the 500 needed a
    real row on the other side of the comparison, not just a bad parameter.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    projection = get_projection_mgr().workflow_execution_list
    for label, hours_ago in (("live-recent", 2), ("live-old", 50)):
        await projection.on_workflow_execution_started(
            {
                "execution_id": label,
                "workflow_id": "wf-1",
                "workflow_name": "Workflow One",
                "started_at": _at(hours_ago),
                "total_phases": 1,
                "inputs": {},
            }
        )

    refused = await _executions_response(started_after=_NAIVE_BOUND)
    assert refused.status_code == 422, "the reported 500 must be gone"

    body = await _executions(started_after=_AWARE_BOUND)
    assert {e["workflow_execution_id"] for e in body["executions"]} == {"live-recent"}
    assert body["total"] == 1
