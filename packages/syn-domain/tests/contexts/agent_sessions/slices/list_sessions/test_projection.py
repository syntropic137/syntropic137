"""Tests for SessionListProjection parent/root session linkage and filtering (#792)."""

from __future__ import annotations

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
