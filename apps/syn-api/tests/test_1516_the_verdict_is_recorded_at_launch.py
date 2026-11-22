"""A degraded start is visible from agent launch, not only after teardown (#1516).

Drives the real `PhaseRuntime` launch hop with the real `SessionCaptureService`
and agentic-workspace reader behind it, then reads the real `/capture/status`
route while the phase's agent is still pending: nothing has finalized, so no
teardown capture verdict exists yet. The start-up verdict must already be
there, and must survive a phase that is abandoned before any capture verdict
is written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from test_1516_a_degraded_start_reaches_the_api import (
    _CLEAN,
    _STORE,
    _container,
    _Recorder,
    _status_row,
)

from syn_adapters.workspace_backends.agentic.session_capture_service import (
    SessionCaptureService,
)
from syn_api.routes.capture import get_capture_status
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_shared.settings.session_store import SessionStoreSettings

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_api.types import CaptureStatusResponse

_EXECUTION = "e-launch"
_PHASE = "p-launch"


class _Workspace:
    execution_id = _EXECUTION
    workspace_id = "w-launch"
    teardown_usage = None

    def __init__(self, status_row: str | None, *, read_breaks: bool) -> None:
        self._exec = _container(
            status_row=status_row, exporter_stdout=_CLEAN, read_breaks=read_breaks
        )

    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> object:
        del working_directory
        return await self._exec(command, timeout_seconds=timeout_seconds, environment=environment)


class _WorkspaceCm:
    async def __aexit__(self, *_exc: object) -> bool:
        return False


async def _launched(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_row: str | None,
    session_id: str = "s-launch",
    url: str | None = _STORE,
    read_breaks: bool = False,
) -> tuple[PhaseRuntime, _Recorder]:
    recorder = _Recorder()
    runtime = PhaseRuntime(
        capture_port=SessionCaptureService(SessionStoreSettings(url=url), "dev", recorder),
        session_store=None,
        writer=None,
        ledger=None,
    )
    runtime.attach_workspace(
        _PHASE,
        workspace=cast("ManagedWorkspace", _Workspace(status_row, read_breaks=read_breaks)),
        workspace_cm=cast("AbstractAsyncContextManager[ManagedWorkspace]", _WorkspaceCm()),
        agent_env={},
        claude_cmd=["claude"],
        delivers_repo_changes=False,
    )
    runtime.launch(_PHASE, session_id=session_id)
    await runtime.record_capability(_PHASE)
    monkeypatch.setattr("syn_api.routes.capture.get_event_store", lambda: recorder)
    return runtime, recorder


async def _read() -> CaptureStatusResponse:
    return await get_capture_status(limit=50, needs_backfill=False, execution_id=_EXECUTION)


@pytest.mark.unit
class TestTheStartIsVisibleWhileTheAgentRuns:
    @pytest.mark.asyncio
    async def test_a_degraded_start_reads_back_before_the_agent_completes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _launched(monkeypatch, status_row=_status_row("degraded", ["store_reachable"], 3))

        response = await _read()

        # No teardown has run: no capture verdict exists yet.
        assert response.entries == []
        [capability] = response.capabilities
        assert capability.capability == "session-store"
        assert capability.status == "degraded"
        assert capability.failed_checks == ["store_reachable"]
        assert capability.doctor_exit == 3
        assert capability.phase_id == _PHASE
        assert capability.capability_status_display == "Capture degraded: store_reachable failed"

    @pytest.mark.asyncio
    async def test_the_start_survives_a_phase_that_records_no_capture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Abandoned with the store down: the teardown sweep records nothing new
        about the start, and the verdict written at launch still explains it."""
        runtime, recorder = await _launched(
            monkeypatch, status_row=_status_row("degraded", ["auth_valid"], 2)
        )
        before = len(recorder.rows)

        await runtime.abandon_phase(_EXECUTION, _PHASE, reason="agent crashed")

        response = await _read()
        assert len(recorder.rows) > before  # teardown still ran its own sweep
        [capability] = response.capabilities
        assert capability.status == "degraded"
        assert capability.failed_checks == ["auth_valid"]

    @pytest.mark.asyncio
    async def test_a_phase_with_no_agent_session_records_nothing_and_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Observations are keyed by session: with none there is nothing to key."""
        _, recorder = await _launched(
            monkeypatch,
            status_row=_status_row("degraded", ["store_reachable"], 3),
            session_id="",
        )

        assert recorder.rows == []

    @pytest.mark.asyncio
    async def test_a_broken_read_does_not_fail_the_launch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _launched(monkeypatch, status_row=None, read_breaks=True)

        assert (await _read()).capabilities == []


@pytest.mark.unit
class TestNothingNewOtherwise:
    @pytest.mark.asyncio
    async def test_a_ready_start_is_recorded_as_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _launched(monkeypatch, status_row=_status_row("ready", [], 0))

        [capability] = (await _read()).capabilities
        assert capability.status == "ready"
        assert capability.capability_status_display == "Capture ready"

    @pytest.mark.asyncio
    async def test_no_store_configured_records_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, recorder = await _launched(
            monkeypatch, status_row=_status_row("degraded", ["store_reachable"], 3), url=None
        )

        assert recorder.rows == []
