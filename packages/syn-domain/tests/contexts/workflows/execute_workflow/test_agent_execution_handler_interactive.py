"""Tests for AgentExecutionHandler's interactive-tmux drive path (issue #771).

Covers:
  * item 1 - a stalled driver round-trip (e.g. a wedged `docker exec`) must
    not hang the execution forever; the wait is bounded by the phase's
    `timeout_seconds` plus a small margin, after which we return a failed
    result with a clear error_reason.
  * item 6 - a successful round-trip records the actual wall-clock duration
    in the session summary instead of a hardcoded `duration_ms=0`.
"""

from __future__ import annotations

import importlib
import threading
import time
from dataclasses import dataclass

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
    TodoAction,
    TodoItem,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)

# NOTE: `handlers/__init__.py` re-exports the *class* `AgentExecutionHandler`,
# shadowing the submodule of the same name on the `handlers` package object.
# `importlib.import_module` reaches into `sys.modules` directly so we get the
# actual module (needed to monkeypatch `_INTERACTIVE_TIMEOUT_MARGIN_SECONDS`)
# rather than the re-exported class.
handler_module = importlib.import_module(
    "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler"
)


@dataclass
class _FakeAwaitResult:
    ready: bool
    reason: str


class _FakeDriver:
    """Duck-typed stand-in for InteractiveTmuxDriver.

    `hang_seconds` models a transport hang: the underlying `await_completion`
    ignores the `timeout` argument it was given (as a real stalled `docker
    exec` would) and blocks for `hang_seconds` before ever returning. Kept
    small (not infinite) so a leaked background thread does not stall
    process/interpreter shutdown after the test moves on.
    """

    def __init__(self, *, hang_seconds: float = 0.0, delay_seconds: float = 0.0) -> None:
        self.hang_seconds = hang_seconds
        self.delay_seconds = delay_seconds
        self.stopped = False

    def send_message(self, agent: str, text: str) -> None:
        pass

    def await_completion(self, agent: str, timeout: float = 0.0) -> _FakeAwaitResult:
        if self.hang_seconds:
            threading.Event().wait(self.hang_seconds)
        elif self.delay_seconds:
            time.sleep(self.delay_seconds)
        return _FakeAwaitResult(ready=True, reason="ready")

    def capture_response(self, agent: str) -> str:
        return "hello from pane"

    def stop(self) -> None:
        self.stopped = True


class _FakeIsolationAdapter:
    def __init__(self, driver: _FakeDriver) -> None:
        self._driver = driver

    def provider_handle(self, handle: object) -> _FakeDriver:
        return self._driver


class _FakeService:
    def __init__(self, driver: _FakeDriver) -> None:
        self._isolation = _FakeIsolationAdapter(driver)


class _FakeWorkspace:
    """Minimal duck-typed ManagedWorkspace stand-in for the interactive path."""

    def __init__(self, driver: _FakeDriver) -> None:
        self._service = _FakeService(driver)
        self.isolation_handle = object()
        self.id = "workspace-1"


@dataclass(frozen=True)
class _SummaryCall:
    """Typed capture of one record_session_summary invocation."""

    total_cost_usd: float | None
    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int
    num_turns: int | None
    duration_ms: int | None
    agent_id: str | None


class _FakeCollector:
    """Captures record_session_summary calls without touching real observability."""

    def __init__(self) -> None:
        self.summary_calls: list[_SummaryCall] = []

    async def record_session_summary(
        self,
        total_cost_usd: float | None,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int,
        cache_read: int,
        num_turns: int | None,
        duration_ms: int | None,
        agent_id: str | None = None,
    ) -> None:
        self.summary_calls.append(
            _SummaryCall(
                total_cost_usd=total_cost_usd,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation=cache_creation,
                cache_read=cache_read,
                num_turns=num_turns,
                duration_ms=duration_ms,
                agent_id=agent_id,
            )
        )


def _make_todo() -> TodoItem:
    return TodoItem(
        execution_id="exec-1",
        action=TodoAction.RUN_AGENT,
        phase_id="phase-1",
        workspace_id="workspace-1",
        session_id="session-1",
    )


@pytest.mark.asyncio
async def test_interactive_driver_hang_fails_within_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled driver round-trip must not wedge the execution forever.

    The driver ignores its `timeout` argument and blocks for longer than
    the bound; the handler must return a failed result well inside
    timeout_seconds + margin, with an error_reason describing the hang.
    """
    monkeypatch.setattr(handler_module, "_INTERACTIVE_TIMEOUT_MARGIN_SECONDS", 0.05)

    driver = _FakeDriver(hang_seconds=1.0)
    workspace = _FakeWorkspace(driver)
    handler = AgentExecutionHandler(controller=None)

    started = time.monotonic()
    result = await handler.handle(
        todo=_make_todo(),
        workspace=workspace,  # type: ignore[arg-type]
        agent_env={},
        claude_cmd=[],
        session_id="session-1",
        agent_model="claude-x",
        timeout_seconds=0,
        collector=None,
        interactive_prompt="do the thing",
        agent_id="claude",
    )
    elapsed = time.monotonic() - started

    # Bounded well under the driver's 1s hang (timeout_seconds=0 + margin=0.05s).
    assert elapsed < 0.5
    assert result.command.exit_code != 0
    assert result.stream_result.error_reason is not None
    assert "did not return within" in result.stream_result.error_reason
    # error_reason reports the bounded timeout (timeout_seconds + margin),
    # matching what was actually enforced.
    assert "transport hang" in result.stream_result.error_reason


@pytest.mark.asyncio
async def test_interactive_round_trip_records_positive_duration() -> None:
    """A successful round-trip must record real wall-clock duration_ms, not 0."""
    driver = _FakeDriver(delay_seconds=0.05)
    workspace = _FakeWorkspace(driver)
    collector = _FakeCollector()
    handler = AgentExecutionHandler(controller=None)

    result = await handler.handle(
        todo=_make_todo(),
        workspace=workspace,  # type: ignore[arg-type]
        agent_env={},
        claude_cmd=[],
        session_id="session-1",
        agent_model="claude-x",
        timeout_seconds=5,
        collector=collector,  # type: ignore[arg-type]
        interactive_prompt="do the thing",
        agent_id="claude",
    )

    assert result.command.exit_code == 0
    assert len(collector.summary_calls) == 1
    assert collector.summary_calls[0].duration_ms is not None
    assert collector.summary_calls[0].duration_ms > 0
