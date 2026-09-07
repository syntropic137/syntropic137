"""`WorkflowExecutionListProjection.page` wires every filter into ONE predicate.

`page` replaced a pair - rows filtered in Python, `total` from a store-level
`COUNT(*)` - that agreed only because both spelled the same single equality
check. These tests assert what that pairing could not guarantee: that adding a
filter to the rows also moves the total and the facets, whichever filter it is.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

pytestmark = pytest.mark.unit

_BASE = datetime(2026, 4, 1, 12, tzinfo=UTC)
_WINDOW_START = _BASE - timedelta(hours=24)


class _FakeStore:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def get_all(self, projection: str) -> list[dict]:
        return list(self._rows)


def _rows() -> list[dict]:
    """24 executions: 14 in the window, 10 outside; statuses every 3, name every 4."""
    return [
        {
            "workflow_execution_id": f"e-{i:02d}",
            "workflow_id": "wf-1",
            "workflow_name": "Nightly Audit" if i % 4 == 0 else "Something Else",
            "status": ("completed", "failed", "running")[i % 3],
            "started_at": (
                _BASE - timedelta(hours=1 + i) if i < 14 else _BASE - timedelta(days=7 + i)
            ).isoformat(),
            "completed_at": None,
            "completed_phases": 1,
            "total_phases": 1,
            "total_tokens": 0,
        }
        for i in range(24)
    ]


def _projection() -> WorkflowExecutionListProjection:
    return WorkflowExecutionListProjection(_FakeStore(_rows()))  # type: ignore[arg-type]


_FILTERS: dict[str, dict] = {
    "none": {},
    "statuses": {"statuses": ["failed"]},
    "window": {"started_after": _WINDOW_START},
    "search": {"search": "nightly"},
    "window+statuses+search": {
        "started_after": _WINDOW_START,
        "statuses": ["completed"],
        "search": "nightly",
    },
}


@pytest.mark.parametrize("label", list(_FILTERS))
async def test_total_matches_the_rows_and_survives_the_page_size(label: str) -> None:
    projection = _projection()
    whole = await projection.page(limit=10_000, **_FILTERS[label])
    sliced = await projection.page(limit=3, **_FILTERS[label])

    assert whole.total == len(whole.rows)
    assert sliced.total == whole.total, (
        f"[{label}] total moved with the page size, so it is describing the "
        "page rather than the collection"
    )
    assert len(sliced.rows) <= 3


@pytest.mark.parametrize("label", list(_FILTERS))
async def test_each_filter_selects_a_proper_subset(label: str) -> None:
    """Guards the test above: a filter that matches everything asserts nothing."""
    page = await _projection().page(limit=10_000, **_FILTERS[label])
    if label == "none":
        assert page.total == 24
    else:
        assert 0 < page.total < 24, f"[{label}] matched {page.total} of 24"


async def test_the_time_window_reaches_the_total_not_just_the_rows() -> None:
    """The exact defect: a windowed query whose count described all of history."""
    page = await _projection().page(started_after=_WINDOW_START, limit=5)
    assert page.total == 14, "24 means the window filtered the rows and not the count"
    assert len(page.rows) == 5
    assert all(r.workflow_execution_id < "e-14" for r in page.rows)


async def test_facets_ignore_the_status_filter_and_honour_the_window() -> None:
    page = await _projection().page(started_after=_WINDOW_START, statuses=["failed"], limit=100)
    # i in 0..13: statuses cycle completed/failed/running -> 5/5/4
    assert page.status_counts == {"completed": 5, "failed": 5, "running": 4}
    assert page.total == 5
    assert sum(page.status_counts.values()) == 14


async def test_pages_partition_the_filtered_collection() -> None:
    projection = _projection()
    seen: list[str] = []
    for page_no in range(1, 4):
        page = await projection.page(started_after=_WINDOW_START, limit=5, offset=(page_no - 1) * 5)
        seen.extend(r.workflow_execution_id for r in page.rows)
    assert len(seen) == len(set(seen)) == 14
