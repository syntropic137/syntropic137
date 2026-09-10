"""The probe must run while the container is still up.

This is the one guarantee `SessionCaptureService` documents but cannot enforce:
it is handed a callable, and a callable stays callable after the workspace is
gone. Exec into a stopped container fails, the service absorbs the failure as
UNKNOWN, and the result is a backfill request for transcripts that were in fact
uploaded - or worse, silence about ones that were not. Nothing downstream can
tell that apart, so the ordering is asserted here, at the only layer that owns
both halves.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.agentic.capture_probe import (
        WorkspaceExecutor,
    )
    from syn_adapters.workspace_backends.agentic.capture_result import (
        AuthoritativeCapture,
    )
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
    )
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

PHASE = "p-1"


class _Workspace:
    """Just enough ManagedWorkspace for the capture call."""

    execution_id = "e-1"
    workspace_id = "w-1"

    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def execute(self, *_a: object, **_k: object) -> object:
        self._log.append("exec")
        return None


class _WorkspaceCm:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def __aenter__(self) -> object:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        self._log.append("teardown")
        return False


class _Capture:
    """Records when it was asked, and exercises the executor it was given."""

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.seen: dict[str, object] = {}

    async def capture_and_record(
        self, execute: WorkspaceExecutor, **kwargs: object
    ) -> AuthoritativeCapture | None:
        self._log.append("capture")
        self.seen = dict(kwargs)
        # Actually call it. A probe that never execs would pass an
        # ordering-only assertion while being useless in production.
        await execute(["apss-session-exporter", "--json"], timeout_seconds=5)
        return None


def _runtime(capture: object, workspace: object, cm: object) -> PhaseRuntime:
    """A runtime holding one phase that has run its agent, and nothing else.

    Both orderings under test live in `PhaseRuntime`, which the processor
    delegates to; building it directly leaves out the workspace service,
    repositories and builders that have nothing to do with the ordering.
    """
    runtime = PhaseRuntime(
        capture_port=cast("SessionCapturePort | None", capture),
        # Delegate import runs on this same path (#895). None here keeps this
        # test about capture ORDERING: with no store there is nothing to
        # import, so the import is a no-op and cannot mask the ordering.
        session_store=None,
        writer=None,
        # No ledger: these tests are about capture ORDER, not billing. The
        # import path treats None as "not wired" and bills the full
        # transcript, which is irrelevant here and covered by
        # test_import_ledger.py.
        ledger=None,
    )
    runtime.attach_workspace(
        PHASE,
        workspace=cast("ManagedWorkspace", workspace),
        workspace_cm=cast("AbstractAsyncContextManager[ManagedWorkspace]", cm),
        agent_env={},
        claude_cmd=[],
    )
    runtime._session_ids[PHASE] = "s-1"  # pyright: ignore[reportPrivateUsage]
    return runtime


async def _finalize(runtime: PhaseRuntime) -> None:
    await runtime.finalize(
        PHASE,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        total_tokens=0,
        duration_seconds=0.0,
    )


class TestCaptureRunsBeforeTeardown:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_probe_execs_before_the_workspace_is_torn_down(self) -> None:
        log: list[str] = []
        capture = _Capture(log)
        await _finalize(_runtime(capture, _Workspace(log), _WorkspaceCm(log)))

        # The exec is what matters, not merely the call: it is the operation
        # that stops working once the container is gone.
        assert log == ["capture", "exec", "teardown"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_capture_is_attributed_to_this_phase(self) -> None:
        log: list[str] = []
        capture = _Capture(log)
        await _finalize(_runtime(capture, _Workspace(log), _WorkspaceCm(log)))

        assert capture.seen["session_id"] == "s-1"
        assert capture.seen["phase_id"] == PHASE
        assert capture.seen["workspace_id"] == "w-1"
        assert capture.seen["execution_id"] == "e-1"
        # The agent ran, so an empty sweep is a gap rather than a success.
        assert capture.seen["expect_sessions"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_teardown_still_happens_when_capture_is_off(self) -> None:
        """None means "no store configured", not "skip cleanup"."""
        log: list[str] = []
        await _finalize(_runtime(None, _Workspace(log), _WorkspaceCm(log)))

        assert log == ["teardown"]


class TestCaptureOnCancelAndFailure:
    """A phase that never finalized still ran an agent.

    Cancel and failure tear workspaces down through `abandon_all`, which
    bypasses `finalize` entirely. Before this was covered, every cancelled or
    failed execution destroyed its spool unprobed - losing exactly the
    transcripts most worth reading.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_cancelled_phase_is_probed_before_teardown(self) -> None:
        log: list[str] = []
        capture = _Capture(log)
        runtime = _runtime(capture, _Workspace(log), _WorkspaceCm(log))

        await runtime.abandon_all("cancel")

        assert log == ["capture", "exec", "teardown"]
        assert capture.seen["session_id"] == "s-1"


class TestTheRealConstructorSetsWhatFinalizeReads:
    """The ordering tests above build the runtime themselves, so they cannot see this.

    They hand `PhaseRuntime` its capture port directly, which means they stay
    green if the PROCESSOR stops passing one down - and the failure in
    production would be capture silently never running. Asserted against the
    real constructor for that reason.
    """

    @pytest.mark.unit
    def test_capture_state_is_initialised(self) -> None:
        p = _make_processor(FakeAgentExecutionHandler())
        runtime = p._runtime  # pyright: ignore[reportPrivateUsage]

        # Defaults to off: a processor built without a capture service must
        # still finalize phases rather than raise.
        assert runtime._capture_port is None  # pyright: ignore[reportPrivateUsage]
        assert runtime._session_ids == {}  # pyright: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_an_injected_service_is_kept(self) -> None:
        capture = _Capture([])
        p = _make_processor(FakeAgentExecutionHandler(), session_capture=capture)

        assert p._runtime._capture_port is capture  # pyright: ignore[reportPrivateUsage]


class TestCaptureCannotFailAPhase:
    """Fail-open is the contract, so it is asserted rather than assumed."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_raising_capture_still_tears_the_workspace_down(self) -> None:
        log: list[str] = []

        class _Exploding:
            async def capture_and_record(self, *_a: object, **_k: object) -> None:
                log.append("boom")
                raise RuntimeError("capture is broken")

        await _finalize(_runtime(_Exploding(), _Workspace(log), _WorkspaceCm(log)))

        # Teardown still happened. A leaked container is a worse outcome than
        # a missing observation, and an hour of agent work must not be lost
        # to a broken telemetry path.
        assert log == ["boom", "teardown"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cancellation_is_not_swallowed(self) -> None:
        """Absorbing CancelledError here would hang shutdown."""
        log: list[str] = []

        class _Cancelled:
            async def capture_and_record(self, *_a: object, **_k: object) -> None:
                raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await _finalize(_runtime(_Cancelled(), _Workspace(log), _WorkspaceCm(log)))
