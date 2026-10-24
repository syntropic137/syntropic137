"""A degraded session store shows while the agent is still running (#1516).

The workspace's start verdict is written by its entrypoint before the agent
can run, and never changes. Reading it only at teardown made "capture
degraded" depend on the phase finishing: a running execution showed nothing,
and a process that died before teardown never recorded it at all.

These drive the REAL processor loop and hold the agent in flight, so the
assertion is made at the moment that matters - between launch and completion -
rather than on a phase that is already over.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.agentic.capability_start import StartCapability
from syn_adapters.workspace_backends.agentic.capture_observation import (
    SESSION_STORE_START_OBSERVATION,
    read_start_verdict_display,
)
from syn_adapters.workspace_backends.agentic.session_capture_service import (
    SessionCaptureService,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler
from syn_shared.settings.session_store import SessionStoreSettings

from .test_processor_smoke import _AN_ANSWER, _make_processor, _one_phase_workflow

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.agentic.capture_probe import WorkspaceExecutor

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _HeldAgent:
    """Launches, then waits to be released before returning a real answer."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self._delegate = FakeAgentExecutionHandler.success(says=_AN_ANSWER)

    async def handle(self, *args: object, **kwargs: object) -> object:
        on_launch = kwargs.get("on_launch")
        if callable(on_launch):
            await on_launch()
            kwargs["on_launch"] = None
        self.entered.set()
        await self.release.wait()
        return await self._delegate.handle(*args, **kwargs)  # pyright: ignore[reportArgumentType]


class _Reader:
    def __init__(self, answer: StartCapability | Exception) -> None:
        self._answer = answer

    async def read(self, execute: WorkspaceExecutor, capability: str) -> StartCapability | None:
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


class _Writer:
    """Keeps what an operator would read off each start row, in order."""

    def __init__(self) -> None:
        self.kinds: list[str] = []
        self.start_displays: list[str | None] = []

    async def record_observation(self, **kwargs: object) -> None:
        data = kwargs["data"]
        assert isinstance(data, dict)
        kind = str(kwargs["observation_type"])
        self.kinds.append(kind)
        if kind == SESSION_STORE_START_OBSERVATION:
            self.start_displays.append(
                read_start_verdict_display(data.get("schema_version"), data.get("start_capability"))
            )


_DEGRADED = StartCapability(
    capability="session-store",
    status="degraded",
    failed_checks=("store_reachable",),
    doctor_exit=3,
)


async def _run_held(reader: _Reader, writer: _Writer, execution_id: str):
    """Run one phase; return the start rows seen mid-flight, and the result."""
    agent = _HeldAgent()
    service = SessionCaptureService(
        SessionStoreSettings(url="http://store:8799"),
        "test",
        writer,
        capability_reader=reader,
    )
    processor = _make_processor(agent, session_capture=service)  # pyright: ignore[reportArgumentType]
    task = asyncio.create_task(
        processor.run(
            workflow_id="wf-1516",
            workflow_name="Degraded start",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id=execution_id,
        )
    )
    try:
        await asyncio.wait_for(agent.entered.wait(), timeout=15)
        assert not task.done()
        in_flight = list(writer.start_displays)
    finally:
        agent.release.set()
    result = await asyncio.wait_for(task, timeout=20)
    return in_flight, result


async def test_the_degraded_verdict_is_recorded_before_the_agent_returns() -> None:
    writer = _Writer()

    in_flight, result = await _run_held(_Reader(_DEGRADED), writer, "exec-1516-degraded")

    assert in_flight == ["Capture degraded: store_reachable failed"], (
        f"no start verdict while the agent was running; rows written: {writer.kinds}"
    )
    # Capture is fail-open: a degraded store never fails the run.
    assert result.status == "completed"


async def test_a_reader_that_raises_does_not_fail_the_run() -> None:
    writer = _Writer()

    in_flight, result = await _run_held(
        _Reader(RuntimeError("status read exploded")), writer, "exec-1516-raises"
    )

    assert in_flight == []
    assert result.status == "completed"
