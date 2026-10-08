"""A RUNNING codex session names its requested model over HTTP (#1785).

Owner feedback 58868cd8: codex sessions on the Sessions page said "unknown".
On the VPS every one of them was a running top-level codex phase with zero
tokens. Codex reports usage once, at the end of its stream, so until then
Lane 2 has no row naming any model - and the read path fell back to Lane 1
tokens and dropped the model SessionStarted had already recorded.

So this test runs the real pieces in the order production does and reads the
answer where the owner did, over HTTP, twice:

1. the real ``SessionLifecycleManager`` starts the session, and the event it
   saves is applied to the real ``SessionListProjection``;
2. the real ``CodexStreamProcessor`` reads the real recording, and is PAUSED
   after ``turn.started`` - before any usage, as on the VPS;
3. ``GET /sessions`` and ``GET /sessions/{id}`` must say the request, labelled
   as one, and must not claim it ran;
4. the stream is released to its end, and the same two reads must now say
   the model codex reported, with the requested label gone.

Doubles are only the edges: the event-store repository, the rollout port, and
the Lane 2 writer/query, which hand rows to the real ``SessionCostProjection``.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.agent_sessions.slices.list_sessions.projection import (
    SessionListProjection,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.test_projection import (
    MockProjectionStore,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_announced_model_is_not_the_requested_one import (
    CODEX_ANNOUNCED,
    REQUESTED_BY_A_CODEX_PHASE,
    _real_rollout,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_model_reaches_the_sessions_read_model import (
    _RECORDING,
    _ObservationsToProjection,
    _RolloutForTheAnnouncedThread,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_event_stream_processor import (
    MockWorkspace,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
    from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
        SessionSummary,
    )

os.environ.setdefault("APP_ENVIRONMENT", "test")

pytestmark = pytest.mark.unit

SESSION_ID = "sess-running-codex"
WORKFLOW_ID = "wf-codex"


class _SavedSessions:
    """A session repository that hands each saved event to the list projection."""

    def __init__(self, projection: SessionListProjection) -> None:
        self._projection = projection

    async def save(self, aggregate: object) -> None:
        for envelope in aggregate.get_uncommitted_events():  # type: ignore[attr-defined]
            event = envelope.event
            if type(event).__name__ == "SessionStartedEvent":
                await self._projection.on_session_started(event.model_dump(mode="json"))


@dataclass
class _NoTools:
    async def get(self, session_id: str) -> list[object]:
        return []


@dataclass
class _Manager:
    session_list: SessionListProjection
    store: InMemoryProjectionStore
    session_tools: _NoTools = field(default_factory=_NoTools)


@dataclass
class _CostQuery:
    """The Lane 2 query seam, answered from the real session_cost projection."""

    projection: SessionCostProjection

    async def get(self, session_id: str) -> SessionCost | None:
        return await self.projection.get_session_cost(session_id)

    async def get_many(self, session_ids: list[str]) -> dict[str, SessionCost]:
        found: dict[str, SessionCost] = {}
        for sid in session_ids:
            cost = await self.projection.get_session_cost(sid)
            if cost is not None:
                found[sid] = cost
        return found


async def _paused_after_turn_started(release: asyncio.Event) -> AsyncIterator[str]:
    """The recording, held after ``turn.started`` until ``release`` is set."""
    for line in _RECORDING.read_text().splitlines():
        yield line
        if '"type":"turn.started"' in line.replace(" ", ""):
            await release.wait()


async def _get(path: str) -> dict[str, object]:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from syn_api.routes.sessions import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


async def _list_row() -> dict[str, object]:
    body = await _get("/sessions?time_window=all")
    sessions = body["sessions"]
    assert isinstance(sessions, list)
    (row,) = [s for s in sessions if isinstance(s, dict) and s.get("id") == SESSION_ID]
    return row


async def test_a_running_codex_session_shows_its_request_then_what_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes import sessions

    store = InMemoryProjectionStore()
    session_list = SessionListProjection(store)
    cost_projection = SessionCostProjection(MockProjectionStore())

    async def _connected() -> None:
        return None

    monkeypatch.setattr(sessions, "ensure_connected", _connected)
    monkeypatch.setattr(sessions, "get_projection_mgr", lambda: _Manager(session_list, store))
    monkeypatch.setattr(sessions, "get_session_cost_query", lambda: _CostQuery(cost_projection))

    lifecycle = SessionLifecycleManager(
        repository=_SavedSessions(session_list),  # type: ignore[arg-type]
        session_id=SESSION_ID,
        workflow_id=WORKFLOW_ID,
        execution_id="exec-1",
        phase_id="p1",
        agent_provider="codex",
        agent_model=REQUESTED_BY_A_CODEX_PHASE,
    )
    await lifecycle.start()
    started: SessionSummary | None = await session_list.get_by_id(SESSION_ID)
    assert started is not None
    assert started.status == "running"

    collector = ObservabilityCollector(
        writer=_ObservationsToProjection(cost_projection),
        session_id=SESSION_ID,
        execution_id="exec-1",
        phase_id="p1",
        workspace_id=None,
        requested_model=REQUESTED_BY_A_CODEX_PHASE,
    )
    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=collector,
        controller=None,
        execution_id="exec-1",
        phase_id="p1",
        session_id=SESSION_ID,
        agent_model=REQUESTED_BY_A_CODEX_PHASE,
        rollout=_RolloutForTheAnnouncedThread(_real_rollout()),
    )
    release = asyncio.Event()
    run = asyncio.create_task(
        processor.process_stream(_paused_after_turn_started(release), MockWorkspace())
    )
    try:
        # Let the processor read up to the pause.
        for _ in range(50):
            await asyncio.sleep(0)

        # Running, no usage yet: the shape every "unknown" on the VPS had.
        running_row = await _list_row()
        running_detail = await _get(f"/sessions/{SESSION_ID}")
        requested_display = f"{REQUESTED_BY_A_CODEX_PHASE} (requested)"
        for served in (running_row, running_detail):
            assert served["status"] == "running"
            assert served["total_tokens"] == 0
            # The request is said, and said to be one. It is never what ran.
            assert served["agent_model"] is None
            assert served["requested_model"] == REQUESTED_BY_A_CODEX_PHASE
            assert served["agent_model_display"] == requested_display
    finally:
        release.set()
        await run

    # The stream ended and codex's rollout named the model: that replaces the
    # request on both surfaces.
    done_row = await _list_row()
    done_detail = await _get(f"/sessions/{SESSION_ID}")
    for served in (done_row, done_detail):
        assert served["agent_model"] == CODEX_ANNOUNCED
        assert served["requested_model"] == REQUESTED_BY_A_CODEX_PHASE
        assert served["agent_model_display"] == CODEX_ANNOUNCED
