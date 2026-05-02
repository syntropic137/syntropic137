"""Unit tests for SessionListProjection.query() -- chunked paging (#730)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import syn_domain.contexts.agent_sessions.slices.list_sessions.projection as proj_module
from syn_domain.contexts.agent_sessions.slices.list_sessions.projection import (
    SessionListProjection,
)

if TYPE_CHECKING:
    import pytest


# ---------------------------------------------------------------------------
# Fake store
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal in-memory projection store for unit tests."""

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._records: list[dict[str, Any]] = list(records or [])
        self.query_call_count = 0

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        for i, r in enumerate(self._records):
            if r.get("id") == key:
                self._records[i] = data
                return
        self._records.append(data)

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        return next((r for r in self._records if r.get("id") == key), None)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        return list(self._records)

    async def delete_all(self, projection: str) -> None:
        self._records.clear()

    async def query(
        self,
        projection: str,
        filters: dict[str, Any] | None = None,
        order_by: str = "",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.query_call_count += 1
        data = list(self._records)

        if filters:
            for k, v in filters.items():
                data = [d for d in data if d.get(k) == v]

        if order_by:
            reverse = order_by.startswith("-")
            key_field = order_by.lstrip("-")
            data = sorted(data, key=lambda d: str(d.get(key_field) or ""), reverse=reverse)

        data = data[offset:]
        if limit:
            data = data[:limit]

        return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session(
    session_id: str,
    status: str = "running",
    started_at: str | None = None,
    workflow_id: str = "wf-1",
) -> dict[str, Any]:
    return {
        "id": session_id,
        "workflow_id": workflow_id,
        "status": status,
        "started_at": started_at,
        "agent_type": "claude",
        "total_tokens": 0,
        "completed_at": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "repos": [],
        "operations": [],
        "subagents": [],
        "subagent_count": 0,
        "tools_by_subagent": {},
    }


def _make_proj(
    records: list[dict[str, Any]] | None = None,
) -> tuple[SessionListProjection, _FakeStore]:
    store = _FakeStore(records)
    return SessionListProjection(store), store


# ---------------------------------------------------------------------------
# 1: fast path — workflow_id only, single store call
# ---------------------------------------------------------------------------


async def test_fast_path_uses_single_store_call_workflow_id_only() -> None:
    """workflow_id only, no statuses/time range → exactly 1 store.query call."""
    records = [_session(f"s-{i}", workflow_id="wf-target") for i in range(5)]
    records += [_session(f"s-other-{i}", workflow_id="wf-other") for i in range(3)]
    proj, store = _make_proj(records)

    results = await proj.query(workflow_id="wf-target")

    assert store.query_call_count == 1
    assert all(r.workflow_id == "wf-target" for r in results)


# ---------------------------------------------------------------------------
# 2: empty statuses list treated as fast path
# ---------------------------------------------------------------------------


async def test_empty_statuses_list_is_fast_path() -> None:
    """statuses=[] is falsy — query uses the fast path (1 store call)."""
    records = [_session(f"s-{i}") for i in range(5)]
    proj, store = _make_proj(records)

    results = await proj.query(statuses=[])

    assert store.query_call_count == 1
    assert len(results) == 5


# ---------------------------------------------------------------------------
# 3: reconcile_orphaned uses fast path (status_filter, not statuses)
# ---------------------------------------------------------------------------


async def test_reconcile_orphaned_uses_fast_path() -> None:
    """reconcile_orphaned calls query with status_filter=, not statuses= — fast path."""
    records = [_session(f"s-run-{i}", status="running") for i in range(3)]
    records += [_session(f"s-done-{i}", status="completed") for i in range(2)]
    proj, store = _make_proj(records)

    query_count_before = store.query_call_count
    count = await proj.reconcile_orphaned()

    assert count == 3
    # query() must make exactly 1 store.query call — status_filter pushes down as
    # an equality filter, so no chunked paging loop is entered.
    assert store.query_call_count - query_count_before == 1


# ---------------------------------------------------------------------------
# 4: statuses multi-filter — only matching returned
# ---------------------------------------------------------------------------


async def test_statuses_filter_returns_only_matching() -> None:
    """statuses=["running"] excludes completed and failed sessions."""
    records = [
        _session("s-run-1", status="running"),
        _session("s-run-2", status="running"),
        _session("s-done-1", status="completed"),
        _session("s-fail-1", status="failed"),
    ]
    proj, _ = _make_proj(records)

    results = await proj.query(statuses=["running"])

    assert {r.id for r in results} == {"s-run-1", "s-run-2"}


# ---------------------------------------------------------------------------
# 5: time window filter
# ---------------------------------------------------------------------------


async def test_time_window_filter_excludes_outside_window() -> None:
    """started_after / started_before excludes sessions outside the time window."""
    records = [
        _session("s-early", started_at="2024-01-01T00:00:00Z"),
        _session("s-in-window", started_at="2024-06-15T00:00:00Z"),
        _session("s-late", started_at="2024-12-31T00:00:00Z"),
    ]
    proj, _ = _make_proj(records)

    after = datetime(2024, 3, 1, tzinfo=UTC)
    before = datetime(2024, 9, 1, tzinfo=UTC)
    results = await proj.query(started_after=after, started_before=before)

    assert len(results) == 1
    assert results[0].id == "s-in-window"


# ---------------------------------------------------------------------------
# 6: chunked paging spans multiple store calls
# ---------------------------------------------------------------------------


async def test_chunked_paging_spans_multiple_store_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When matching records are spread past the first chunk, multiple store calls are made."""
    # Reduce chunk size so test doesn't need hundreds of records
    monkeypatch.setattr(proj_module, "_MIN_CHUNK_SIZE", 10)
    monkeypatch.setattr(proj_module, "_CHUNK_SIZE_MULTIPLIER", 2)

    # 25 records: first 15 are "completed" (won't match), last 10 are "running"
    # chunk_size = max(10, 5*2) = 10, target = 0 + 5 = 5
    # Chunk 1: records 0-9 (all "completed") -> 0 matched -> continue
    # Chunk 2: records 10-19 (5 "completed", 5 "running") -> 5 matched -> target reached
    records = [_session(f"s-done-{i}", status="completed") for i in range(15)]
    records += [_session(f"s-run-{i}", status="running") for i in range(10)]
    proj, store = _make_proj(records)

    results = await proj.query(statuses=["running"], limit=5)

    assert store.query_call_count >= 2, "Expected multiple store calls for chunked paging"
    assert len(results) == 5
    assert all(r.status == "running" for r in results)


# ---------------------------------------------------------------------------
# 7: safety cap stops loop and logs warning
# ---------------------------------------------------------------------------


async def test_safety_cap_stops_loop_and_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When _SAFETY_CAP_ROWS rows are scanned without enough matches, log a warning."""
    monkeypatch.setattr(proj_module, "_MIN_CHUNK_SIZE", 10)
    monkeypatch.setattr(proj_module, "_SAFETY_CAP_ROWS", 30)

    # 40 records, none with status "running" — forces the cap after 30 scanned
    records = [_session(f"s-{i}", status="completed") for i in range(40)]
    proj, _ = _make_proj(records)

    with caplog.at_level(
        logging.WARNING,
        logger=("syn_domain.contexts.agent_sessions.slices.list_sessions.projection"),
    ):
        results = await proj.query(statuses=["running"], limit=5)

    assert results == []
    assert any("safety cap" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 8: offset returns correct slice of filtered results
# ---------------------------------------------------------------------------


async def test_offset_returns_correct_slice_of_filtered_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """offset applies to post-filtered results, not raw store rows."""
    monkeypatch.setattr(proj_module, "_MIN_CHUNK_SIZE", 5)

    # 20 running sessions; order by id (lexicographic: s-00 … s-19)
    records = [_session(f"s-{i:02d}", status="running") for i in range(20)]
    proj, _ = _make_proj(records)

    results = await proj.query(statuses=["running"], limit=5, offset=10, order_by="id")

    assert len(results) == 5
    assert [r.id for r in results] == ["s-10", "s-11", "s-12", "s-13", "s-14"]


# ---------------------------------------------------------------------------
# 9: result count bounded by limit
# ---------------------------------------------------------------------------


async def test_result_count_bounded_by_limit() -> None:
    """query() never returns more than limit records even with many matches."""
    records = [_session(f"s-{i}", status="running") for i in range(50)]
    proj, _ = _make_proj(records)

    results = await proj.query(statuses=["running"], limit=10)

    assert len(results) <= 10
