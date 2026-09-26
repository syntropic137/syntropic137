"""The agent's git credential is renewed for exactly as long as the agent runs (#725).

The renewal schedule itself is tested in syn-adapters against a fake clock.
What is tested here is the hop into it: the REAL handler holds the keeper
open around the agent's stream, and nowhere else, and a lapse the keeper
reports reaches Lane 2 as an event the observability write gate accepts.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
    _credential_lapse_reporter,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_shared.events import GIT_CREDENTIAL_LAPSED, VALID_EVENT_TYPES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.workspace_backends.service.credential_keeper import CredentialLapse

pytestmark = pytest.mark.unit

_PHASE_ID = "implement"


class _Lapse:
    """A CredentialLapse's shape, without importing the adapter at runtime."""

    def __init__(self) -> None:
        self.expired_at = datetime(2026, 9, 26, 13, 0, tzinfo=UTC)
        self.attempts = 7
        self.last_error = "GitHub said no"


class _Recorded:
    def __init__(self, kind: str, data: object) -> None:
        self.kind = kind
        self.data = data


class _Writer:
    def __init__(self) -> None:
        self.recorded: list[_Recorded] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: object,
        data: object,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        kind = str(getattr(observation_type, "value", observation_type))
        self.recorded.append(_Recorded(kind, data))


class _Workspace:
    """Records the order in which the keeper and the agent's stream start and stop."""

    id = "ws-1"
    last_stream_exit_code = 0

    def __init__(self) -> None:
        self.timeline: list[str] = []

    def stream(self, *_args: object, **_kwargs: object) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            self.timeline.append("agent started")
            yield '{"type": "result", "result": "done", "usage": {}}'
            self.timeline.append("agent finished")

        return gen()

    async def interrupt(self) -> bool:
        return True

    @contextlib.asynccontextmanager
    async def keep_git_credential_fresh(self, **_kwargs: object) -> AsyncIterator[None]:
        self.timeline.append("keeper started")
        try:
            yield
        finally:
            self.timeline.append("keeper stopped")


class TestTheKeeperSpansTheAgentsRun:
    async def test_it_starts_before_the_agent_and_stops_after_it(self) -> None:
        workspace = _Workspace()

        await AgentExecutionHandler(controller=None).handle(
            todo=TodoItem(execution_id="exec-1", action=TodoAction.RUN_AGENT, phase_id=_PHASE_ID),
            workspace=workspace,  # type: ignore[arg-type]
            agent_env={},
            claude_cmd=["claude"],
            session_id="sess-1",
            agent_model="claude-opus-4-20250514",
            timeout_seconds=3600,
            collector=None,
        )

        assert workspace.timeline == [
            "keeper started",
            "agent started",
            "agent finished",
            "keeper stopped",
        ]


class TestALapseReachesLaneTwo:
    async def test_it_is_recorded_as_an_event_the_write_gate_accepts(self) -> None:
        writer = _Writer()
        collector = ObservabilityCollector(
            writer=writer,  # type: ignore[arg-type]
            session_id="sess-1",
            execution_id="exec-1",
            phase_id=_PHASE_ID,
            workspace_id="ws-1",
            requested_model="claude-opus-4-20250514",
        )

        await _credential_lapse_reporter(_PHASE_ID, collector)(
            _Lapse()  # type: ignore[arg-type]
        )

        (recorded,) = writer.recorded
        assert recorded.kind == GIT_CREDENTIAL_LAPSED
        assert recorded.kind in VALID_EVENT_TYPES
        assert recorded.data == {
            "expired_at": "2026-09-26T13:00:00+00:00",
            "attempts": 7,
            "last_error": "GitHub said no",
        }

    async def test_it_is_a_phase_warning_even_with_no_collector(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            lapse: CredentialLapse = _Lapse()  # type: ignore[assignment]
            await _credential_lapse_reporter(_PHASE_ID, None)(lapse)

        assert f"[PHASE {_PHASE_ID}]" in caplog.text
        assert "expired" in caplog.text
