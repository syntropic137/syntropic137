"""Tests for SessionListProjection parent/root session linkage and filtering (#792)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.contexts.agent_sessions.slices.list_sessions.projection import (
    SessionListProjection,
)


class _FakeStore:
    """Minimal in-memory projection store stand-in for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    async def save(self, projection: str, key: str, data: dict) -> None:
        self._data[key] = data

    async def get(self, projection: str, key: str) -> dict | None:
        return self._data.get(key)

    async def get_all(self, projection: str) -> list[dict]:
        return list(self._data.values())

    async def query(
        self,
        projection: str,
        filters: dict | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        results = list(self._data.values())
        if filters:
            for key, value in filters.items():
                results = [r for r in results if r.get(key) == value]
        return results[offset : offset + limit] if limit else results[offset:]


def _session_started_event(session_id: str, parent_session_id: str | None = None) -> dict:
    return {
        "session_id": session_id,
        "workflow_id": "wf-1",
        "phase_id": "phase-1",
        "execution_id": "exec-1",
        "agent_provider": "claude",
        "started_at": "2026-07-28T00:00:00Z",
        "parent_session_id": parent_session_id,
        "root_session_id": parent_session_id or session_id,
        "repos": [],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_session_started_persists_parent_and_root_session_id() -> None:
    """on_session_started persists parent_session_id and root_session_id from event data."""
    store = _FakeStore()
    projection = SessionListProjection(store)

    await projection.on_session_started(
        _session_started_event("child-1", parent_session_id="parent-1")
    )

    summaries = await projection.get_all()
    assert len(summaries) == 1
    assert summaries[0].parent_session_id == "parent-1"
    assert summaries[0].root_session_id == "parent-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_session_started_without_parent_yields_none() -> None:
    """A top-level session (no parent) persists None for parent_session_id."""
    store = _FakeStore()
    projection = SessionListProjection(store)

    await projection.on_session_started(_session_started_event("parent-1"))

    summaries = await projection.get_all()
    assert summaries[0].parent_session_id is None
    assert summaries[0].root_session_id == "parent-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_query_filters_by_parent_session_id() -> None:
    """query(parent_session_id=...) returns only that parent's children."""
    store = _FakeStore()
    projection = SessionListProjection(store)

    await projection.on_session_started(_session_started_event("parent-1"))
    await projection.on_session_started(
        _session_started_event("child-1", parent_session_id="parent-1")
    )
    await projection.on_session_started(
        _session_started_event("child-2", parent_session_id="parent-1")
    )
    await projection.on_session_started(
        _session_started_event("other-child", parent_session_id="parent-2")
    )

    children = await projection.query(parent_session_id="parent-1")

    assert {s.id for s in children} == {"child-1", "child-2"}


# ---------------------------------------------------------------------------
# page(): rows, total and facets from one filtered sequence (#1160)
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 4, 1, 12, tzinfo=UTC)
_WINDOW_START = _BASE - timedelta(hours=24)


def _seed_rows() -> list[dict]:
    """24 sessions: 14 in the window, 10 outside; statuses every 3, id-match every 4."""
    return [
        {
            "id": ("needle" if i % 4 == 0 else "other") + f"-{i:02d}",
            "workflow_id": "wf-1",
            "agent_type": "claude",
            "status": ("completed", "failed", "running")[i % 3],
            "started_at": (
                _BASE - timedelta(hours=1 + i) if i < 14 else _BASE - timedelta(days=7 + i)
            ).isoformat(),
            "completed_at": None,
            "total_tokens": 0,
        }
        for i in range(24)
    ]


async def _paged_projection() -> SessionListProjection:
    store = _FakeStore()
    for row in _seed_rows():
        await store.save("session_summaries", row["id"], row)
    return SessionListProjection(store)


_PAGE_FILTERS: dict[str, dict] = {
    "none": {},
    "statuses": {"statuses": ["failed"]},
    "window": {"started_after": _WINDOW_START},
    "search": {"search": "needle"},
    "window+statuses+search": {
        "started_after": _WINDOW_START,
        "statuses": ["completed"],
        "search": "needle",
    },
}


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("label", list(_PAGE_FILTERS))
async def test_page_total_matches_the_rows_and_survives_the_page_size(label: str) -> None:
    """Every filter must reach the rows, the total and the facets alike."""
    projection = await _paged_projection()
    whole = await projection.page(limit=10_000, **_PAGE_FILTERS[label])
    sliced = await projection.page(limit=3, **_PAGE_FILTERS[label])

    assert whole.total == len(whole.rows)
    assert sliced.total == whole.total
    assert len(sliced.rows) <= 3
    if label != "none":
        assert 0 < whole.total < 24, f"[{label}] matched {whole.total} of 24"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_page_reaches_rows_beyond_the_first_page() -> None:
    """The rows the endpoint could not address at any parameter setting (#1160)."""
    projection = await _paged_projection()
    first = await projection.page(limit=10, offset=0)
    second = await projection.page(limit=10, offset=10)

    assert {s.id for s in first.rows}.isdisjoint({s.id for s in second.rows})
    assert first.total == second.total == 24


@pytest.mark.unit
@pytest.mark.asyncio
async def test_page_facets_ignore_the_status_filter_and_honour_the_window() -> None:
    projection = await _paged_projection()
    page = await projection.page(started_after=_WINDOW_START, statuses=["failed"], limit=100)

    assert page.status_counts == {"completed": 5, "failed": 5, "running": 4}
    assert page.total == 5
    assert sum(page.status_counts.values()) == 14, (
        "the facets must count the window's 14, not all 24 and not the 5 selected"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_page_excludes_an_undated_session_from_rows_total_and_facets_alike() -> None:
    """A row that cannot be placed in time is out of a bounded window everywhere."""
    store = _FakeStore()
    await store.save(
        "session_summaries",
        "dated",
        {
            "id": "dated",
            "workflow_id": "wf-1",
            "status": "completed",
            "started_at": (_BASE - timedelta(hours=1)).isoformat(),
        },
    )
    await store.save(
        "session_summaries",
        "undated",
        {"id": "undated", "workflow_id": "wf-1", "status": "pending", "started_at": None},
    )
    projection = SessionListProjection(store)

    bounded = await projection.page(started_after=_WINDOW_START, limit=100)
    assert [s.id for s in bounded.rows] == ["dated"]
    assert bounded.total == 1
    assert bounded.status_counts == {"completed": 1}

    unbounded = await projection.page(limit=100)
    assert {s.id for s in unbounded.rows} == {"dated", "undated"}
    assert unbounded.total == 2
    assert unbounded.status_counts == {"completed": 1, "pending": 1}
