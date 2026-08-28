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
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.agentic.capture_probe import (
        WorkspaceExecutor,
    )
    from syn_adapters.workspace_backends.agentic.capture_result import (
        AuthoritativeCapture,
    )

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


def _processor(capture: object, workspace: object, cm: object) -> WorkflowExecutionProcessor:
    """Build the processor without its full dependency graph.

    _finalize_phase touches a known, small set of attributes. Constructing the
    real object would drag in a workspace service, repositories and builders
    that have nothing to do with the ordering under test.
    """
    p = object.__new__(WorkflowExecutionProcessor)
    p._session_managers = {}  # type: ignore[attr-defined]
    p._active_workspaces = {PHASE: workspace}  # type: ignore[attr-defined]
    p._phase_session_ids = {PHASE: "s-1"}  # type: ignore[attr-defined]
    p._active_envs = {}  # type: ignore[attr-defined]
    p._active_cmds = {}  # type: ignore[attr-defined]
    p._active_workspace_cms = {PHASE: cm}  # type: ignore[attr-defined]
    p._session_capture = capture  # type: ignore[attr-defined]
    # Delegate import runs on this same path (#895). None here keeps this
    # test about capture ORDERING: with no store there is nothing to import,
    # so the import is a no-op and cannot mask the ordering under test.
    p._session_store = None  # type: ignore[attr-defined]
    p._observability_writer = None  # type: ignore[attr-defined]
    p._phase_leader_native_ids = {}  # type: ignore[attr-defined]
    return p


async def _finalize(p: WorkflowExecutionProcessor) -> None:
    await p._finalize_phase(  # pyright: ignore[reportPrivateUsage]
        PHASE,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        total_tokens=0,
        duration=0.0,
    )


class TestCaptureRunsBeforeTeardown:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_probe_execs_before_the_workspace_is_torn_down(self) -> None:
        log: list[str] = []
        capture = _Capture(log)
        await _finalize(_processor(capture, _Workspace(log), _WorkspaceCm(log)))

        # The exec is what matters, not merely the call: it is the operation
        # that stops working once the container is gone.
        assert log == ["capture", "exec", "teardown"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_capture_is_attributed_to_this_phase(self) -> None:
        log: list[str] = []
        capture = _Capture(log)
        await _finalize(_processor(capture, _Workspace(log), _WorkspaceCm(log)))

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
        await _finalize(_processor(None, _Workspace(log), _WorkspaceCm(log)))

        assert log == ["teardown"]


class TestCaptureOnCancelAndFailure:
    """A phase that never finalized still ran an agent.

    Cancel and failure tear workspaces down through
    _close_phase_workspace_cms, which bypasses _finalize_phase entirely. Before
    this was covered, every cancelled or failed execution destroyed its spool
    unprobed - losing exactly the transcripts most worth reading.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_cancelled_phase_is_probed_before_teardown(self) -> None:
        log: list[str] = []
        capture = _Capture(log)
        p = _processor(capture, _Workspace(log), _WorkspaceCm(log))

        await p._close_phase_workspace_cms("cancel")  # pyright: ignore[reportPrivateUsage]

        assert log == ["capture", "exec", "teardown"]
        assert capture.seen["session_id"] == "s-1"


class TestTheRealConstructorSetsWhatFinalizeReads:
    """The ordering tests above bypass __init__, so they cannot see this.

    They populate the attributes directly, which means they stay green if the
    constructor stops setting one - and the failure in production would be an
    AttributeError inside teardown, or capture silently never running. Asserted
    against the REAL constructor for that reason.
    """

    @pytest.mark.unit
    def test_capture_state_is_initialised(self) -> None:
        p = _make_processor(FakeAgentExecutionHandler())

        # Defaults to off: a processor built without a capture service must
        # still finalize phases rather than raise.
        assert p._session_capture is None  # pyright: ignore[reportPrivateUsage]
        assert p._phase_session_ids == {}  # pyright: ignore[reportPrivateUsage]

    @pytest.mark.unit
    def test_an_injected_service_is_kept(self) -> None:
        capture = _Capture([])
        p = _make_processor(FakeAgentExecutionHandler(), session_capture=capture)

        assert p._session_capture is capture  # pyright: ignore[reportPrivateUsage]


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

        await _finalize(_processor(_Exploding(), _Workspace(log), _WorkspaceCm(log)))

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
            await _finalize(_processor(_Cancelled(), _Workspace(log), _WorkspaceCm(log)))
