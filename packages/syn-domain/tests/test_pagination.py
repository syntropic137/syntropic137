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

from syn_domain.pagination import Page, matches_search, paginate, within_window

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
        base_predicate=lambda r: (
            within_window(r.started_at, started_after, None)
            and matches_search(search, r.id, r.name)
        ),
        status_of=lambda r: r.status,
        statuses=statuses,
        sort_key=lambda r: r.started_at or "",
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
            base_predicate=lambda r: within_window(r.started_at, after, None),
            status_of=lambda r: r.status,
            statuses=None,
            sort_key=lambda r: r.started_at or "",
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


def test_unpaged_is_the_whole_collection() -> None:
    page = Page.unpaged(_RECORDS, status_of=lambda r: r.status)
    assert page.total == len(_RECORDS) == len(page.rows)
    assert sum(page.status_counts.values()) == len(_RECORDS)
