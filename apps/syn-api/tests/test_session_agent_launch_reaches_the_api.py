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


async def test_a_streaming_agent_is_active_only_while_it_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real launch producer, read by the driver while the stream is open (B0).

    ``AgentExecutionHandler`` and ``AgentLaunchEvidence`` decide when
    ``AgentLaunched`` is written; nothing here marks the launch by hand. The
    stream is held open after the agent's first line, which is the state the
    load driver samples in: a launch fact settled only at exit read
    ``unknown`` here and counted a working agent as idle.
    """
    import asyncio
    from collections.abc import AsyncIterator
    from unittest.mock import MagicMock, patch

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from syn_api.routes import sessions
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        announce_as,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        StreamResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionHandler,
    )
    from syn_perf.loadtest import driver

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

    app = FastAPI()
    app.include_router(sessions.router)
    agent_spoke = asyncio.Event()
    agent_done = asyncio.Event()

    async def _stream(
        *_args: object, wrapper_name: str | None = None, **_kwargs: object
    ) -> AsyncIterator[str]:
        assert wrapper_name is not None
        yield announce_as(wrapper_name)
        yield '{"type": "assistant", "message": {"content": []}}'
        await agent_done.wait()

    class _Processor:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def process_stream(
            self, stream: AsyncIterator[str], workspace: object
        ) -> StreamResult:
            del workspace
            async for _ in stream:
                agent_spoke.set()
            return StreamResult(line_count=1, interrupt_requested=False, interrupt_reason=None)

    workspace = MagicMock()
    workspace.stream = _stream
    workspace.last_stream_exit_code = 0

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        async def _working() -> bool:
            session = await driver._session(client, SESSION_ID)
            assert session is not None
            return session.agent_working

        # SessionStarted is saved before provisioning: running, never counted.
        await lifecycle.start()
        assert await _agent_launch() == "unknown"
        assert not await _working()

        path = (
            "syn_domain.contexts.orchestration.slices.execute_workflow"
            ".handlers.AgentExecutionHandler.EventStreamProcessor"
        )
        with patch(path, _Processor):
            phase = asyncio.create_task(
                AgentExecutionHandler(controller=None).handle(
                    todo=TodoItem(
                        execution_id="exec-1",
                        action=TodoAction.RUN_AGENT,
                        phase_id="p1",
                        session_id=SESSION_ID,
                    ),
                    workspace=workspace,
                    agent_env={},
                    claude_cmd=["claude", "-p"],
                    session_id=SESSION_ID,
                    agent_model=None,
                    timeout_seconds=300,
                    on_launch=lifecycle.mark_launched,
                )
            )
            try:
                await asyncio.wait_for(agent_spoke.wait(), 5)
                # The stream is still open: the agent is working right now.
                assert await _agent_launch() == "launched"
                assert await _working()
            finally:
                agent_done.set()
                await phase

        # The phase ended and its session completed: no longer counted.
        await lifecycle.complete_failure(error_message="agent exited")
        assert not await _working()
