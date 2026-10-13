"""``GET /sessions/{id}`` says whether the agent process has started (#1717).

A session is ``running`` from ``SessionStarted``, which is saved before the
phase's workspace is provisioned. So ``status`` cannot answer "is an agent
working in this phase", and the load-test driver counted provisioning phases
as concurrent agents. The answer the domain already records is
``AgentLaunched`` (#1065), kept by ``session_summaries`` as ``agent_launch``;
it was dropped at the API boundary.

The real ``SessionLifecycleManager`` writes the events, the real
``SessionListProjection`` applies them, and the answer is read over HTTP: the
consumer, not the model the field was added to.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.agent_sessions.slices.list_sessions.projection import (
    SessionListProjection,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost

os.environ.setdefault("APP_ENVIRONMENT", "test")

pytestmark = pytest.mark.unit

SESSION_ID = "sess-provisioning-then-launched"


def _snake(event_type: str) -> str:
    """``AgentLaunched`` -> ``on_agent_launched`` (AutoDispatchProjection's rule)."""
    return "on" + "".join(f"_{c.lower()}" if c.isupper() else c for c in event_type)


class _ProjectedSessions:
    """A session repository that applies each saved event to the list projection."""

    def __init__(self, projection: SessionListProjection) -> None:
        self._projection = projection

    async def save(self, aggregate: object) -> None:
        for envelope in aggregate.get_uncommitted_events():  # type: ignore[attr-defined]
            event = envelope.event
            handler = getattr(self._projection, _snake(event.event_type), None)
            if handler is not None:
                await handler(event.model_dump(mode="json"))
        aggregate.mark_events_as_committed()  # type: ignore[attr-defined]


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
class _NoCost:
    async def get(self, session_id: str) -> SessionCost | None:
        return None

    async def get_many(self, session_ids: list[str]) -> dict[str, SessionCost]:
        return {}


async def _agent_launch() -> str:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from syn_api.routes.sessions import SessionResponse, router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/sessions/{SESSION_ID}")
    assert response.status_code == 200, response.text
    body = SessionResponse.model_validate_json(response.content)
    assert body.status == "running"
    return response.json()["agent_launch"]


async def test_a_running_session_is_launched_only_after_agent_launched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes import sessions

    store = InMemoryProjectionStore()
    session_list = SessionListProjection(store)

    async def _connected() -> None:
        return None

    monkeypatch.setattr(sessions, "ensure_connected", _connected)
    monkeypatch.setattr(sessions, "get_projection_mgr", lambda: _Manager(session_list, store))
    monkeypatch.setattr(sessions, "get_session_cost_query", lambda: _NoCost())

    lifecycle = SessionLifecycleManager(
        repository=_ProjectedSessions(session_list),  # type: ignore[arg-type]
        session_id=SESSION_ID,
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="p1",
        agent_provider="claude",
        agent_model=None,
    )

    # SessionStarted is saved before provisioning: running, not yet launched.
    await lifecycle.start()
    assert await _agent_launch() == "unknown"

    # The stream observed the process.
    await lifecycle.mark_launched()
    assert await _agent_launch() == "launched"
