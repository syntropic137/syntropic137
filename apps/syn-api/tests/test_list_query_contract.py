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

`GET /artifacts` (#1204) was the severest form of both: a bare JSON array with
no envelope, so there was no `total` to be wrong - a response of 50 rows was
indistinguishable from a collection of 50, and a client could not detect
truncation at all. `page` and `page_size` were undeclared and silently dropped,
`limit` capped at 200, and `phase_id` and `artifact_type` were applied in Python
to whatever rows that cap returned. On the running system 200 artifacts reached
34 hours back while 1000+ existed.

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

from syn_api.list_query import MAX_PAGE_SIZE

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


async def _seed_artifact(
    row_id: str,
    *,
    artifact_type: str = "other",
    created_at: str | None,
    workflow_id: str = "wf-1",
    phase_id: str | None = "phase-1",
    name: str = "Deliverable",
) -> None:
    """One artifact row, written straight into the projection's store.

    ``created_at`` is the artifact's principal timestamp, the one the window
    bounds; artifacts have no start time, which is why the parameter is spelled
    ``created_after`` rather than ``started_after``.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()
    await manager.artifact_list._store.save(
        "artifact_summaries",
        row_id,
        {
            "id": row_id,
            "workflow_id": workflow_id,
            "execution_id": "ex-1",
            "session_id": None,
            "phase_id": phase_id,
            "artifact_type": artifact_type,
            "name": name,
            "created_at": created_at,
            "size_bytes": 12,
            "content": "irrelevant",
            "content_hash": None,
            "is_primary_deliverable": True,
            "source_path": None,
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


class _ArtifactPage(NamedTuple):
    """The envelope ``/artifacts`` answers with, read as fields not keys.

    A ``Mapping[str, Any]`` would type nothing and spend the untyped-dicts
    budget to say less than this does. The page has four numbers and a facet
    tally, and every assertion below is about one of them; the rows are only
    ever asked for their ids, so that is what is kept.
    """

    ids: list[str]
    total: int
    page: int
    page_size: int
    type_counts: Mapping[str, int]
    excluded_undated: int


async def _artifacts(**params: QueryValue) -> _ArtifactPage:
    body = await _get("syn_api.routes.artifacts", "/artifacts", **params)
    return _ArtifactPage(
        ids=[a["id"] for a in body["artifacts"]],
        total=body["total"],
        page=body["page"],
        page_size=body["page_size"],
        type_counts=body["type_counts"],
        # Read by key, so a field the response model declares but the endpoint
        # forgets to pass fails here rather than defaulting quietly to 0.
        excluded_undated=body["excluded_undated"],
    )


async def _artifacts_response(**params: QueryValue) -> Response:
    return await _request("syn_api.routes.artifacts", "/artifacts", **params)


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
async def test_the_window_says_how_many_rows_it_could_not_place_in_time(name: str):
    """(#1215) Excluding them is right; not saying so is the defect.

    The response above is indistinguishable from one where `no-start` simply
    fell outside the bound, and on `/artifacts` that ambiguity hid a quarter of
    the corpus. `excluded_undated` is the field that separates the two, and it
    is on every surface that takes a window because every one of them can be
    handed a row with no timestamp.

    Two undated rows against five dated ones: the count is not the page size,
    not the total, and not the number of rows the bound rejected (which is 2 as
    well for `started_after`, hence the `started_before` half - there it is 3).
    """
    surface = _SURFACES[name]
    await _seed_across_the_bound(surface)
    await surface.seed("no-start-a", status="pending", started_at=None)
    await surface.seed("no-start-b", status="pending", started_at=None)

    lower = await surface.get(started_after=_AWARE_BOUND)
    assert lower["total"] == 3
    assert lower["excluded_undated"] == 2

    upper = await surface.get(started_before=_AWARE_BOUND)
    assert upper["total"] == 2
    assert upper["excluded_undated"] == 2

    unbounded = await surface.get()
    assert unbounded["total"] == 7
    assert unbounded["excluded_undated"] == 0, (
        "with no bound nothing is unjudgeable - the undated rows are returned, "
        "so reporting them as excluded would be the opposite lie"
    )


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


# -- #1204: /artifacts answers about the collection, not about 50 rows --------
#
# The fixture size is the whole point of this section. Every bug in this class -
# here, #1159 and #1160 - survived because no fixture was ever larger than one
# page, which made "fetch one page" and "fetch everything" the same program.
# `_ARTIFACT_ROWS` is deliberately more than three pages of `_ARTIFACT_PAGE`.

_ARTIFACT_PAGE = 50
_ARTIFACT_ROWS = 173

#: The per-request cap. Capping one response is fine; capping what is reachable
#: is the defect, so this is asserted as a page size and never as a ceiling.
MAX_ARTIFACT_PAGE_SIZE = MAX_PAGE_SIZE


async def _seed_artifact_collection(count: int = _ARTIFACT_ROWS) -> None:
    """`count` artifacts, newest first by id: a-000 is the newest."""
    for i in range(count):
        await _seed_artifact(f"a-{i:03d}", created_at=_at(i * 0.1))


async def test_artifact_total_exceeds_the_rows_it_returned():
    """(a) The regression guard: `total` must be the collection, not the page.

    173 artifacts exist and 50 come back. A `total` of 50 - which is what
    `len(rows)` produces, and what a bare array implies by having no total at
    all - says "you have them all" while 123 are unreached. Neither number can
    arise by accident: 173 is not the page size and 50 is not the collection.
    """
    await _seed_artifact_collection()

    body = await _artifacts(page_size=_ARTIFACT_PAGE)

    assert len(body.ids) == _ARTIFACT_PAGE
    assert body.total == _ARTIFACT_ROWS, (
        "total must count every matching artifact. 50 means it describes the "
        "page, which is the defect; a missing key means the endpoint still "
        "answers with a bare array and truncation is undetectable"
    )


async def test_artifact_total_is_invariant_under_page_size():
    """(b) The property that distinguishes a real count from a page length.

    A page length changes with `page_size` by definition. A count does not.
    Asserting them together is what makes the difference visible: at page_size
    1 a `len(rows)` total reads 1, at 50 it reads 50, and only the invariant
    number is the one a client can page against.
    """
    await _seed_artifact_collection()

    totals = {size: (await _artifacts(page_size=size)).total for size in (1, 10, 50)}

    assert totals == {1: _ARTIFACT_ROWS, 10: _ARTIFACT_ROWS, 50: _ARTIFACT_ROWS}, (
        f"total moved with page_size: {totals}. A number that tracks the page "
        "is the page length under a count's name"
    )
    assert len((await _artifacts(page_size=1)).ids) == 1, (
        "page_size must also SELECT rows, or an invariant total is only "
        "invariant because nothing is being paged"
    )


async def test_artifact_paging_arithmetic_closes_on_the_last_page():
    """(c) Every row is on exactly one page, and the last page is short.

    173 over 50 is 4 pages: 50 + 50 + 50 + 23. If the arithmetic closes AND the
    union of the pages is the whole collection, no row is unreachable and none
    is served twice - which is the property "at most 200 are reachable, ever"
    violated.
    """
    await _seed_artifact_collection()

    pages = [
        await _artifacts(page_size=_ARTIFACT_PAGE, page=n)
        for n in range(1, _ARTIFACT_ROWS // _ARTIFACT_PAGE + 2)
    ]
    last = pages[-1]

    assert len(pages) == 4
    assert (len(pages) - 1) * _ARTIFACT_PAGE + len(last.ids) == _ARTIFACT_ROWS
    assert len(last.ids) == 23
    assert last.total == _ARTIFACT_ROWS

    seen = [row_id for one_page in pages for row_id in one_page.ids]
    assert len(seen) == len(set(seen)), "a row appeared on two pages"
    assert set(seen) == {f"a-{i:03d}" for i in range(_ARTIFACT_ROWS)}


async def test_artifact_page_two_is_a_different_page():
    """(d) `page` must select rows rather than be accepted and discarded.

    Supplying `page=2` returned byte-identical first rows, which is worse than
    rejecting it: a client that pages silently re-reads page 1 forever.
    """
    await _seed_artifact_collection()

    first = set((await _artifacts(page_size=_ARTIFACT_PAGE, page=1)).ids)
    second = set((await _artifacts(page_size=_ARTIFACT_PAGE, page=2)).ids)

    assert len(first) == len(second) == _ARTIFACT_PAGE
    assert not (first & second), "page 2 returned page 1"


async def test_artifact_row_201_is_reachable():
    """The ceiling the issue measured: no parameter combination reached row 201.

    `limit` capped at 200 and there was no offset, so the 201st artifact was
    unreachable at any setting. A per-request cap on `page_size` is fine; a cap
    on what exists is not.
    """
    await _seed_artifact_collection(260)

    body = await _artifacts(page_size=MAX_ARTIFACT_PAGE_SIZE, page=2)

    assert body.total == 260
    assert "a-200" in set(body.ids), (
        "the 201st artifact must be addressable; it was not at any limit"
    )
    assert body.ids[-1] == "a-259"


async def test_artifact_empty_is_distinguishable_from_truncated():
    """(f) Zero rows and a truncated page are different answers.

    A bare array could not express the difference: `[]` and a 50-row array both
    described an unknown collection. The envelope carries the number that
    settles it, and `total == 0` is the ONLY case where the rows are all of
    them.
    """
    empty = await _artifacts(page_size=_ARTIFACT_PAGE)
    assert empty.ids == []
    assert empty.total == 0

    await _seed_artifact_collection()
    truncated = await _artifacts(page_size=_ARTIFACT_PAGE)
    assert len(truncated.ids) == _ARTIFACT_PAGE
    assert truncated.total > len(truncated.ids)

    filtered_to_nothing = await _artifacts(page_size=_ARTIFACT_PAGE, artifact_type="no-such-type")
    assert filtered_to_nothing.ids == []
    assert filtered_to_nothing.total == 0, (
        "an empty page of a non-empty collection must still report 0 matches, "
        "not the size of the collection the filter was applied to"
    )


async def test_artifact_window_bounds_the_total_as_well_as_the_rows():
    """The window is a filter on the collection, not on the page.

    60 artifacts inside the window and 60 outside it. A `total` of 120 means
    the bound reached the rows but not the count - or never arrived at all,
    which is what an undeclared query parameter looks like from outside.
    """
    for i in range(60):
        await _seed_artifact(f"recent-{i:03d}", created_at=_at(1 + i * 0.1))
    for i in range(60):
        await _seed_artifact(f"old-{i:03d}", created_at=_at(48 + i))

    body = await _artifacts(page_size=_ARTIFACT_PAGE, created_after=_AWARE_BOUND)

    assert body.total == 60
    assert len(body.ids) == _ARTIFACT_PAGE
    assert all(row_id.startswith("recent-") for row_id in body.ids)

    rest = await _artifacts(page_size=_ARTIFACT_PAGE, page=2, created_after=_AWARE_BOUND)
    assert len(rest.ids) == 10
    assert rest.total == 60


@pytest.mark.parametrize("bound", ["created_after", "created_before"])
async def test_artifact_timezone_less_bound_is_refused_with_the_same_message(bound: str):
    """(e) The #1186 refusal, reached through the artifacts route.

    The same `WindowBound` the other two surfaces use, so the same value means
    the same thing on all three: a bound with no offset is ambiguous and is
    handed back with the fix in it, not read as UTC and answered confidently.
    """
    await _seed_artifact_collection(5)

    rejection = _rejection(await _artifacts_response(**{bound: _NAIVE_BOUND}))

    assert rejection.startswith(f"{bound}: ")
    assert "timezone" in rejection
    assert "2026-09-01T00:00:00Z" in rejection, (
        "the message must show a value that WOULD work, not just refuse this one"
    )


async def test_artifact_aware_bounds_still_answer_and_still_filter():
    """The refusal is about the missing offset and nothing else.

    Without this, "refuses every bound" passes the test above.
    """
    for i in range(3):
        await _seed_artifact(f"after-{i}", created_at=_at(1 + i))
    for i in range(2):
        await _seed_artifact(f"before-{i}", created_at=_at(30 + i))

    for spelling in (_AWARE_BOUND, "2026-03-31T12:00:00Z", "2026-03-31T14:00:00+02:00"):
        body = await _artifacts(created_after=spelling)
        assert set(body.ids) == {"after-0", "after-1", "after-2"}, spelling
        assert body.total == 3, spelling

    upper = await _artifacts(created_before=_AWARE_BOUND)
    assert set(upper.ids) == {"before-0", "before-1"}
    assert upper.total == 2


async def test_artifact_type_filter_searches_the_collection_not_the_page():
    """The filter used to run in Python over whatever the store's cap returned.

    5 plans sit behind 120 newer reports. Filtered after a page of 50, the
    answer is "no plans"; filtered where the total is computed, it is 5. The
    type counts describe the other types because the facet ignores the type
    filter itself.
    """
    for i in range(120):
        await _seed_artifact(f"report-{i:03d}", artifact_type="report", created_at=_at(1 + i * 0.1))
    for i in range(5):
        await _seed_artifact(f"plan-{i}", artifact_type="plan", created_at=_at(90 + i))

    body = await _artifacts(page_size=_ARTIFACT_PAGE, artifact_type="plan")

    assert set(body.ids) == {f"plan-{i}" for i in range(5)}, (
        "the type filter must select from the collection; applied to the newest "
        "page it finds none of these"
    )
    assert body.total == 5
    assert body.type_counts == {"report": 120, "plan": 5}


async def test_artifact_search_narrows_the_rows_and_the_total_together():
    """Search happens where `total` is computed, or the two describe different sets."""
    for i in range(4):
        await _seed_artifact(f"needle-{i}", created_at=_at(1), name="Nightly Audit")
    for i in range(8):
        await _seed_artifact(f"other-{i}", created_at=_at(1), name="Something Else")

    body = await _artifacts(q="nightly")

    assert set(body.ids) == {f"needle-{i}" for i in range(4)}
    assert body.total == 4


async def test_artifact_limit_is_a_deprecated_alias_that_page_size_overrides():
    """`limit` keeps working for the published CLI flag; `page_size` wins.

    `limit` was the only parameter this endpoint ever honoured, so removing it
    would break every existing caller. It survives as an alias with the same
    precedence rule the sessions endpoint settled.
    """
    await _seed_artifact_collection(120)

    alias_only = await _artifacts(limit=10)
    assert len(alias_only.ids) == 10
    assert alias_only.page_size == 10
    assert alias_only.total == 120, "the alias must not turn the count back into a page length"

    both = await _artifacts(limit=10, page_size=25)
    assert len(both.ids) == 25, "page_size must win over limit"
    assert both.page_size == 25

    neither = await _artifacts()
    assert len(neither.ids) == _ARTIFACT_PAGE
    assert neither.page_size == _ARTIFACT_PAGE


async def test_artifacts_written_by_the_real_producer_page_the_same_way():
    """The issue's own repro, from the event that actually writes the row.

    The seeding helper writes the projection's store directly, so it could
    agree with the endpoint and disagree with production: `created_at` is
    stamped by `on_artifact_created` and read by the window, and a value
    dropped at that hop passes every test that checks either end. 120 rows so
    the collection is larger than a page.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    projection = get_projection_mgr().artifact_list
    for i in range(120):
        await projection.on_artifact_created(
            {
                "artifact_id": f"live-{i:03d}",
                "workflow_id": "wf-live",
                "execution_id": "ex-live",
                "phase_id": "implement",
                "artifact_type": "deliverable",
                "title": f"Deliverable {i}",
                "content": "x",
                "created_at": _at(i),
            }
        )

    body = await _artifacts(page_size=_ARTIFACT_PAGE)
    assert body.total == 120
    assert len(body.ids) == _ARTIFACT_PAGE

    windowed = await _artifacts(page_size=_ARTIFACT_PAGE, created_after=_AWARE_BOUND)
    assert windowed.total == 25, (
        "the window must reach rows the real writer produced: 25 of the 120 are "
        "inside 24 hours (the bound is inclusive). 120 means created_at never "
        "arrived at the comparator"
    )
    assert len(windowed.ids) == 25


# -- V10: /artifacts says how many rows the window could not judge (#1215) -----
#
# 274 of 1037 artifacts carry `created_at: null` - every one written before
# ArtifactCreated v4 (#920) gave the event a timestamp of its own. They are
# returned by an unfiltered list and cannot satisfy any bound, so
# `?created_after=7d` answered 755 and the reader had no way to learn that 274
# of the 282 missing rows were dropped for being unjudgeable rather than old.
#
# The write path is already closed - the aggregate stamps `datetime.now(UTC)`
# unconditionally - so these rows are a fixed historical set, not a growing
# one. What was still open is the reporting.


async def _seed_undated_artifact_via_the_real_producer(row_id: str) -> None:
    """One undated row, written by the handler that wrote the real 274.

    Not the seeding helper: that writes the store directly and would agree
    with the endpoint while disagreeing with production. This is a pre-v4
    ``ArtifactCreated`` payload - the key is ABSENT, exactly as it is in the
    events already in the store - fed to the projection handler that reads it.
    A `created_at` defaulted anywhere on that hop makes the row datable and
    this fixture stops being undated at all.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    await get_projection_mgr().artifact_list.on_artifact_created(
        {
            "artifact_id": row_id,
            "workflow_id": "wf-live",
            "execution_id": "ex-live",
            "phase_id": "implement",
            "artifact_type": "deliverable",
            "title": f"Deliverable {row_id}",
            "content": "x",
        }
    )


async def test_artifacts_undated_rows_are_counted_where_the_reader_can_see_them():
    """The issue's own numbers, in miniature: 6 dated, 3 undated, 1 too old.

    A window returning 5 of 10 could mean five things; `excluded_undated` says
    which. The three numbers are deliberately distinct - total 5, excluded 3,
    gap 5 - so an implementation that returned the gap, the count of rows the
    bound rejected, or a constant fails.
    """
    for i in range(5):
        await _seed_artifact(f"recent-{i}", created_at=_at(1 + i))
    await _seed_artifact("ancient", created_at=_at(400))
    for i in range(3):
        await _seed_undated_artifact_via_the_real_producer(f"undated-{i}")

    windowed = await _artifacts(created_after=_AWARE_BOUND)

    assert windowed.total == 5
    assert windowed.excluded_undated == 3, (
        "the endpoint must report the rows it could not place in time. 0 means "
        "the count never left the domain page - the response is rebuilt field "
        "by field on the way out and a new one is dropped unless it is named"
    )
    assert windowed.total - len(windowed.ids) == 0


async def test_artifacts_an_undated_row_is_still_absent_from_a_window():
    """(b) Current behaviour, kept. Reporting them is not admitting them.

    A 24-hour query that returns rows of unknown age answers a question nobody
    asked. The rows, the total and the type facets must still agree about them.
    """
    await _seed_artifact("dated", created_at=_at(1), artifact_type="deliverable")
    await _seed_undated_artifact_via_the_real_producer("undated")

    windowed = await _artifacts(created_after=_AWARE_BOUND)

    assert windowed.ids == ["dated"]
    assert windowed.total == 1
    assert windowed.type_counts == {"deliverable": 1}, (
        "an undated row tallied into the facets would promise a row that "
        "selecting that type does not return"
    )


async def test_artifacts_an_undated_row_is_still_returned_unfiltered():
    """(c) Current behaviour, kept - and the reason the gap was invisible.

    The unfiltered list was always honest; only the filtered one lost rows. So
    an unbounded query returns the undated row AND reports nothing excluded,
    because with no bound there is nothing it failed to judge.
    """
    await _seed_artifact("dated", created_at=_at(1))
    await _seed_undated_artifact_via_the_real_producer("undated")

    unfiltered = await _artifacts()

    assert set(unfiltered.ids) == {"dated", "undated"}
    assert unfiltered.total == 2
    assert unfiltered.excluded_undated == 0


async def test_artifacts_the_excluded_count_survives_paging():
    """It describes the query, so it must not move with `page_size` or `page`.

    Same rule `total` lives under (#1204, #1159): a number that changes with
    the slice is a page length wearing a collection's name. Checked on a page
    that holds none of the rows in question, since that is where a count
    derived from `rows` would collapse.
    """
    for i in range(30):
        await _seed_artifact(f"recent-{i:02d}", created_at=_at(1 + i * 0.1))
    for i in range(7):
        await _seed_undated_artifact_via_the_real_producer(f"undated-{i}")

    for page_size in (5, 30, 100):
        body = await _artifacts(page_size=page_size, created_after=_AWARE_BOUND)
        assert body.total == 30, page_size
        assert body.excluded_undated == 7, page_size

    last = await _artifacts(page_size=25, page=2, created_after=_AWARE_BOUND)
    assert len(last.ids) == 5
    assert last.total == 30
    assert last.excluded_undated == 7
