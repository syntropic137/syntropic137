"""A finished session keeps its duration when Lane 2 has no row for it (#975 item 1).

Lane 2 (``session_cost``) is enrichment: it can be missing a session that
Lane 1 knows completed. Both read paths used to take a terminal session's
duration from Lane 2 alone, so such a session read ``duration_seconds: null``
and ``duration_display: "—"`` although ``started_at`` and ``completed_at``
were right there on the domain row.

Each case drives the real HTTP endpoint functions, list and detail, with only
the projection manager and the Lane 2 query stubbed, so a hop that drops the
derived value between the rule and the response fails here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from syn_api import prefix_resolver
from syn_api.routes import sessions
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
    SessionSummary as DomainSessionSummary,
)
from syn_domain.pagination import Page

os.environ.setdefault("APP_ENVIRONMENT", "test")

pytestmark = pytest.mark.unit

_SESSION_ID = "sess-975"
_STARTED = datetime(2026, 11, 13, 9, 0, 0, tzinfo=UTC)
# 754.5 s: not a round number, and nothing but the two timestamps produces it.
_COMPLETED = _STARTED + timedelta(seconds=754.5)


def _session(
    status: str = "completed",
    started_at: datetime | None = _STARTED,
    completed_at: datetime | None = _COMPLETED,
) -> DomainSessionSummary:
    return DomainSessionSummary(
        id=_SESSION_ID,
        workflow_id="",
        agent_type="claude",
        status=status,
        total_tokens=0,
        started_at=started_at,
        completed_at=completed_at,
    )


@dataclass
class _SessionList:
    session: DomainSessionSummary

    async def get_by_id(self, session_id: str) -> DomainSessionSummary | None:
        return self.session if session_id == self.session.id else None

    async def page(self, **_: object) -> Page[DomainSessionSummary]:
        return Page(rows=[self.session], total=1, status_counts={self.session.status: 1})


@dataclass
class _SessionTools:
    async def get(self, session_id: str) -> list[object]:
        return []


@dataclass
class _Manager:
    session_list: _SessionList
    session_tools: _SessionTools = field(default_factory=_SessionTools)
    store: object = None


@dataclass
class _CostQuery:
    cost: SessionCost | None

    async def get(self, session_id: str) -> SessionCost | None:
        return self.cost

    async def get_many(self, session_ids: list[str]) -> dict[str, SessionCost]:
        return {self.cost.session_id: self.cost} if self.cost is not None else {}


async def _noop() -> None:
    return None


async def _resolve(_store: object, _namespace: str, partial_id: str, _label: str) -> str:
    return partial_id


def _wire(
    monkeypatch: pytest.MonkeyPatch, session: DomainSessionSummary, cost: SessionCost | None
) -> None:
    manager = _Manager(session_list=_SessionList(session))
    monkeypatch.setattr(sessions, "ensure_connected", _noop)
    monkeypatch.setattr(sessions, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(sessions, "get_session_cost_query", lambda: _CostQuery(cost))
    monkeypatch.setattr(prefix_resolver, "resolve_or_raise", _resolve)


async def _list_row() -> sessions.SessionSummaryResponse:
    listing = await sessions.list_sessions_endpoint(
        workflow_id=None,
        execution_id=None,
        status=None,
        statuses=None,
        started_after=None,
        started_before=None,
        q=None,
        page=1,
        page_size=50,
        limit=None,
    )
    (row,) = listing.sessions
    return row


async def _both(
    monkeypatch: pytest.MonkeyPatch, session: DomainSessionSummary, cost: SessionCost | None
) -> tuple[sessions.SessionSummaryResponse, sessions.SessionResponse]:
    _wire(monkeypatch, session, cost)
    return await _list_row(), await sessions.get_session_endpoint(_SESSION_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "failed"])
async def test_a_finished_session_with_no_lane2_row_takes_its_duration_from_lane1(
    status: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed, detail = await _both(monkeypatch, _session(status=status), cost=None)

    assert listed.duration_seconds == 754.5
    assert detail.duration_seconds == 754.5
    assert listed.duration_display == detail.duration_display
    assert listed.duration_display != "—"


@pytest.mark.asyncio
async def test_lane2_duration_wins_when_it_has_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deliberately different from the timestamps, so the source is unambiguous.
    cost = SessionCost(session_id=_SESSION_ID, duration_ms=42_000)

    listed, detail = await _both(monkeypatch, _session(), cost)

    assert listed.duration_seconds == 42.0
    assert detail.duration_seconds == 42.0


@pytest.mark.asyncio
async def test_a_running_session_is_still_measured_against_the_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = datetime.now(UTC) - timedelta(minutes=30)
    # A stale Lane 2 value must not freeze a live session's duration.
    cost = SessionCost(session_id=_SESSION_ID, duration_ms=1_000)

    listed, detail = await _both(
        monkeypatch, _session(status="running", started_at=started, completed_at=None), cost
    )

    for duration in (listed.duration_seconds, detail.duration_seconds):
        assert duration is not None
        assert 1800 <= duration < 1900


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("started_at", "completed_at"),
    [(None, _COMPLETED), (_STARTED, None), (None, None)],
    ids=["no-start", "no-completion", "neither"],
)
async def test_without_both_timestamps_or_lane2_the_duration_is_unknown(
    started_at: datetime | None, completed_at: datetime | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed, detail = await _both(
        monkeypatch, _session(started_at=started_at, completed_at=completed_at), cost=None
    )

    assert listed.duration_seconds is None
    assert detail.duration_seconds is None
    assert listed.duration_display == detail.duration_display == "—"
