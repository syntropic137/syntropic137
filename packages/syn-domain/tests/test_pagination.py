"""`paginate` must derive rows, total and facets from one filtered sequence.

The bug this exists to prevent is not a wrong number, it is two numbers that
were computed by different code. `/executions` filtered its rows in Python and
counted its total with a store-level `COUNT(*)`; both spelled `status ==` and
so agreed, right up until a second filter dimension was added to one of them.

So these tests assert the RELATIONSHIP between the three outputs, not their
values in one scenario. A filter added to the row predicate and forgotten in
the count breaks the relationship whatever the values are.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.pagination import Page, coerce_datetime, matches_search, paginate, within_window

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Rec:
    id: str
    status: str
    started_at: str | None
    name: str


_BASE = datetime(2026, 4, 1, 12, tzinfo=UTC)


def _hours_ago(h: float) -> str:
    return (_BASE - timedelta(hours=h)).isoformat()


#: 30 records: 18 inside a 24h window, 12 outside; three statuses cycling every
#: 3; a searchable name every 4. Status and searchability are deliberately
#: co-prime so no filter is a proxy for another - correlate them and a facet
#: tally that collapsed onto the selected status would still look right.
_RECORDS = [
    _Rec(
        id=f"r-{i:02d}",
        status=("completed", "failed", "running")[i % 3],
        started_at=_hours_ago(1 + i) if i < 18 else _hours_ago(48 + i),
        name="Nightly Audit" if i % 4 == 0 else "Something Else",
    )
    for i in range(30)
]

_WINDOW_START = _BASE - timedelta(hours=24)

_FILTERS = {
    "none": {},
    "single status": {"statuses": ["failed"]},
    "multi status": {"statuses": ["failed", "running"]},
    "window": {"started_after": _WINDOW_START},
    "search": {"search": "nightly"},
    "window+statuses+search": {
        "started_after": _WINDOW_START,
        "statuses": ["completed"],
        "search": "nightly",
    },
}

_LARGE = 10_000


def _page(
    *,
    statuses: list[str] | None = None,
    started_after: datetime | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> Page[_Rec]:
    return paginate(
        _RECORDS,
        base_predicate=lambda r: matches_search(search, r.id, r.name),
        status_of=lambda r: r.status,
        statuses=statuses,
        timestamp_of=lambda r: r.started_at,
        after=started_after,
        to_row=lambda r: r,
        offset=offset,
        limit=limit,
    )


@pytest.mark.parametrize("label", list(_FILTERS))
def test_total_equals_the_rows_when_nothing_is_sliced_off(label: str) -> None:
    """Uncapped, `total` and `len(rows)` are the same collection counted twice."""
    page = _page(limit=_LARGE, **_FILTERS[label])
    assert page.total == len(page.rows), (
        f"[{label}] total and rows came from different predicates - this is the "
        "shape of #1119, and it appears the moment a filter reaches one and not "
        "the other"
    )


@pytest.mark.parametrize("label", list(_FILTERS))
def test_total_does_not_change_with_the_page_size(label: str) -> None:
    """`total` describes the collection, so slicing must not move it."""
    small = _page(limit=4, **_FILTERS[label])
    large = _page(limit=_LARGE, **_FILTERS[label])
    assert small.total == large.total
    assert len(small.rows) <= 4


@pytest.mark.parametrize("label", list(_FILTERS))
def test_the_filters_actually_bite(label: str) -> None:
    """Guards the tests above: a predicate that matches everything proves nothing."""
    page = _page(limit=_LARGE, **_FILTERS[label])
    if label == "none":
        assert page.total == len(_RECORDS)
    else:
        assert 0 < page.total < len(_RECORDS), (
            f"[{label}] matched {page.total} of {len(_RECORDS)} - a filter that "
            "selects all or nothing makes the consistency assertions vacuous"
        )


@pytest.mark.parametrize("label", list(_FILTERS))
def test_status_counts_sum_to_the_total_only_when_no_status_is_selected(label: str) -> None:
    """The facets are the base collection; `total` is that collection filtered by status."""
    page = _page(limit=_LARGE, **_FILTERS[label])
    selected = _FILTERS[label].get("statuses")
    facet_sum = sum(page.status_counts.values())
    if selected is None:
        assert facet_sum == page.total
    else:
        assert facet_sum > page.total, (
            f"[{label}] the facets collapsed onto the selected status - every "
            "unselected chip would read 0 and the operator could not see what "
            "switching would return"
        )
        assert page.total == sum(page.status_counts.get(s, 0) for s in selected)


def test_pages_partition_the_collection() -> None:
    """Consecutive pages are disjoint and together are the whole match."""
    seen: list[str] = []
    total = _page(limit=_LARGE).total
    for page_no in range(1, 5):
        page = _page(limit=8, offset=(page_no - 1) * 8)
        seen.extend(r.id for r in page.rows)
        assert page.total == total
    assert len(seen) == len(set(seen)), "a row appeared on two pages"
    assert set(seen) == {r.id for r in _RECORDS}


def test_rows_are_newest_first() -> None:
    page = _page(limit=_LARGE)
    starts = [r.started_at for r in page.rows]
    assert starts == sorted(starts, reverse=True)


def test_a_record_with_no_timestamp_is_out_of_a_bounded_window_and_in_an_unbounded_one() -> None:
    """Rows, total and facets must agree about a row they cannot place in time.

    A count that includes rows the query excludes tells the caller to page
    towards something that is not there (#920).
    """
    records = [
        _Rec(id="dated", status="completed", started_at=_hours_ago(1), name="x"),
        _Rec(id="undated", status="pending", started_at=None, name="x"),
    ]

    def run(after: datetime | None) -> Page[_Rec]:
        return paginate(
            records,
            base_predicate=lambda _r: True,
            status_of=lambda r: r.status,
            statuses=None,
            timestamp_of=lambda r: r.started_at,
            after=after,
            to_row=lambda r: r,
            limit=_LARGE,
        )

    bounded = run(_WINDOW_START)
    assert [r.id for r in bounded.rows] == ["dated"]
    assert bounded.total == 1
    assert bounded.status_counts == {"completed": 1}

    unbounded = run(None)
    assert {r.id for r in unbounded.rows} == {"dated", "undated"}
    assert unbounded.total == 2
    assert unbounded.status_counts == {"completed": 1, "pending": 1}


# -- The exclusion is right; being SILENT about it was not (#1215) -------------
#
# 274 of 1037 artifacts carry no `created_at`, so `?created_after=7d` reported
# 755 and the reader had no way to tell that 274 of the missing 282 were
# dropped for being unjudgeable rather than for being old. Excluding them stays
# - a 24h window that returns rows of unknown age answers a different question
# - but the count of what could not be judged has to come back with the page.

#: 10 records: 6 dated inside the window, 1 dated outside it, 3 undated. The
#: undated ones do not share a status, so a tally that collapsed onto one
#: status, or onto "everything that is not in `rows`", gets a different number
#: from the right one.
_MIXED = [
    _Rec(id="in-a", status="completed", started_at=_hours_ago(1), name="Nightly Audit"),
    _Rec(id="in-b", status="completed", started_at=_hours_ago(2), name="Other"),
    _Rec(id="in-c", status="failed", started_at=_hours_ago(3), name="Other"),
    _Rec(id="in-d", status="failed", started_at=_hours_ago(4), name="Other"),
    _Rec(id="in-e", status="running", started_at=_hours_ago(5), name="Other"),
    _Rec(id="in-f", status="running", started_at=_hours_ago(6), name="Other"),
    _Rec(id="old", status="completed", started_at=_hours_ago(400), name="Other"),
    _Rec(id="undated-a", status="completed", started_at=None, name="Nightly Audit"),
    _Rec(id="undated-b", status="failed", started_at=None, name="Other"),
    _Rec(id="undated-c", status="failed", started_at=None, name="Other"),
]


def _mixed_page(
    *,
    statuses: list[str] | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    search: str | None = None,
) -> Page[_Rec]:
    return paginate(
        _MIXED,
        base_predicate=lambda r: matches_search(search, r.id, r.name),
        status_of=lambda r: r.status,
        statuses=statuses,
        timestamp_of=lambda r: r.started_at,
        after=started_after,
        before=started_before,
        to_row=lambda r: r,
        limit=_LARGE,
    )


def test_a_window_reports_how_many_rows_it_could_not_judge() -> None:
    """The number the response was missing: excluded because undated (#1215).

    Asserted as a value, not as `total`-minus-something, because the whole
    defect was that the two exclusions were indistinguishable by arithmetic.
    `old` is dropped as well and must NOT be in this count.
    """
    page = _mixed_page(started_after=_WINDOW_START)

    assert page.total == 6
    assert page.excluded_undated == 3
    assert {r.id for r in page.rows} == {"in-a", "in-b", "in-c", "in-d", "in-e", "in-f"}


def test_an_upper_bound_alone_also_reports_them() -> None:
    """Either bound makes the window judgeable-or-not; it is not an `after` quirk."""
    assert _mixed_page(started_before=_BASE).excluded_undated == 3


def test_an_unbounded_query_excludes_nothing_and_returns_the_undated_rows() -> None:
    """Current behaviour, kept: with no window there is nothing to fail.

    This is the half that already worked - the undated rows were never lost
    from the unfiltered list, only from the filtered one - so it is pinned
    rather than changed.
    """
    page = _mixed_page()

    assert page.total == len(_MIXED)
    assert page.excluded_undated == 0
    assert {r.id for r in page.rows} == {r.id for r in _MIXED}


def test_the_undated_rows_stay_out_of_the_rows_the_total_and_the_facets() -> None:
    """Reporting them is not including them: a bounded window still excludes.

    Returning a row of unknown age from a 24-hour query would be a different
    untruth, so the three outputs must still agree about it (#920).
    """
    page = _mixed_page(started_after=_WINDOW_START)

    assert "undated-a" not in {r.id for r in page.rows}
    assert page.total == len(page.rows)
    assert sum(page.status_counts.values()) == page.total, (
        "an undated row was tallied into the facets - the chip would promise a "
        "row that selecting that status does not return"
    )


def test_the_count_is_narrowed_by_the_other_filters_just_as_the_total_is() -> None:
    """`excluded_undated` answers for THIS query, not for the whole store.

    It sits next to `total` and is read against it, so it has to be counted
    over the same filters. A tally taken before them would report 3 here and
    invite the reader to add it to a total that was counted over 1.
    """
    searched = _mixed_page(started_after=_WINDOW_START, search="nightly")
    assert searched.total == 1, "guard: the search has to actually narrow"
    assert searched.excluded_undated == 1

    by_status = _mixed_page(started_after=_WINDOW_START, statuses=["failed"])
    assert by_status.total == 2, "guard: the status filter has to actually narrow"
    assert by_status.excluded_undated == 2


def test_the_count_is_not_the_gap_between_two_totals() -> None:
    """The gap conflates "too old" with "undated" - that gap IS the bug.

    1037 - 755 = 282 was the only number available and it was 274 undated rows
    plus 8 genuinely older ones. Here the same arithmetic gives 4 and the
    honest answer is 3, so a `total`-difference implementation fails.
    """
    windowed = _mixed_page(started_after=_WINDOW_START)
    all_time = _mixed_page()

    assert all_time.total - windowed.total == 4
    assert windowed.excluded_undated == 3


def test_unpaged_is_the_whole_collection() -> None:
    page = Page.unpaged(_RECORDS, status_of=lambda r: r.status)
    assert page.total == len(_RECORDS) == len(page.rows)
    assert sum(page.status_counts.values()) == len(_RECORDS)


# -- A timestamp is a UTC instant however it was spelled (#1183) ---------------
#
# `within_window` compared the bound straight against the row, and Python
# raises `TypeError` comparing an aware datetime with a naive one. Either side
# could arrive without an offset - the bound from a hand-edited
# `?started_after=2026-04-01T00:00:00` that FastAPI parsed without complaint,
# the row from an event whose producer omitted one - so the mismatch is
# symmetric and both halves reached the same 500.
#
# The API now refuses a bound with no offset (`syn_api.list_query.WindowBound`),
# but that guards one caller and one half. The comparison itself has to be
# total: nothing checks a ROW for an offset, and `page()` and `query()` are
# reachable from callers that are not HTTP requests.

_AWARE = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
_NAIVE = datetime(2026, 4, 1, 12, 0)


def test_a_timezone_less_value_is_the_same_instant_as_its_utc_spelling() -> None:
    """The contract, stated once: a missing offset means UTC.

    Equality rather than "is aware": `astimezone` also returns something aware,
    and on a host that is not UTC it returns a different instant.
    """
    assert coerce_datetime(_NAIVE) == _AWARE
    assert coerce_datetime("2026-04-01T12:00:00") == _AWARE
    assert coerce_datetime("2026-04-01T12:00:00Z") == _AWARE
    assert coerce_datetime("2026-04-01T14:00:00+02:00") == _AWARE


def test_an_unparseable_value_is_still_nothing() -> None:
    assert coerce_datetime("not a timestamp") is None
    assert coerce_datetime(None) is None
    assert coerce_datetime(1743508800) is None


@pytest.mark.parametrize(
    ("row", "after", "before"),
    [
        pytest.param("2026-04-01T12:00:00+00:00", _NAIVE, None, id="naive-lower-aware-row"),
        pytest.param("2026-04-01T12:00:00+00:00", None, _NAIVE, id="naive-upper-aware-row"),
        pytest.param("2026-04-01T12:00:00", _AWARE, None, id="aware-lower-naive-row"),
        pytest.param("2026-04-01T12:00:00", None, _AWARE, id="aware-upper-naive-row"),
        pytest.param("2026-04-01T12:00:00", _NAIVE, _NAIVE, id="naive-both-naive-row"),
    ],
)
def test_either_side_may_omit_the_offset(
    row: str, after: datetime | None, before: datetime | None
) -> None:
    """Every mixture of aware and naive, on both sides, in both directions.

    The row sits exactly on the bound in each case, so an answer at all means
    the comparison happened AND placed the two values at the same instant.
    Before the fix, four of these five raised `TypeError`.
    """
    assert within_window(row, after, before) is True


def test_a_timezone_less_bound_excludes_the_rows_outside_it() -> None:
    """Not crashing is not the assertion: the bound still has to select.

    A bound that was coerced but then ignored, or widened to cover everything,
    passes the row-on-the-bound cases above and fails here.
    """
    assert within_window("2026-04-01T11:59:59+00:00", _NAIVE, None) is False
    assert within_window("2026-04-01T12:00:01+00:00", None, _NAIVE) is False
