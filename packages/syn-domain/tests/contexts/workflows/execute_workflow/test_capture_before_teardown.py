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

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)

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
    p._active_prompts = {}  # type: ignore[attr-defined]
    p._active_workspace_cms = {PHASE: cm}  # type: ignore[attr-defined]
    p._shared_workspaces = {}  # type: ignore[attr-defined]
    p._session_capture = capture  # type: ignore[attr-defined]
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
