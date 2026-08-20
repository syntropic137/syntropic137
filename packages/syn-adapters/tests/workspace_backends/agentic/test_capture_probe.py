"""The host-side probe, and the two rules it must never break.

1. It never raises. Capture is fail-open: a transcript that did not reach the
   store must not turn an hour of successful agent work into a failed phase.
2. Not knowing is never success. Every path that cannot get an answer returns a
   state whose needs_backfill is true, because "we could not find out" and "it
   is safely stored" must not be the same value.
"""

from __future__ import annotations

import json

import pytest

from syn_adapters.workspace_backends.agentic.capture_probe import (
    EXPORTER_PROBE_COMMAND,
    PROBE_STATE_FILE,
    probe_capture,
)
from syn_adapters.workspace_backends.agentic.capture_result import CaptureExpectations
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)

_EXPECT = CaptureExpectations(
    store_url="http://store:8799", deployment="syntropic137__dev", expect_sessions=True
)

_CLEAN = json.dumps(
    {
        "schema_version": 1,
        "scs_version": "1.0",
        "captured_everything": True,
        "store_url": "http://store:8799",
        "origin": {"environment": "container", "deployment": "syntropic137__dev"},
        "counters": {
            "discovered": 1,
            "skipped_unchanged": 0,
            "uploaded": 1,
            "accepted": 1,
            "duplicate": 0,
            "rejected": 0,
            "skipped_oversize": 0,
            "failed": 0,
            "unconfirmed": 0,
        },
    }
)


def _result(stdout: str, exit_code: int, *, timed_out: bool = False) -> ExecutionResult:
    return ExecutionResult(
        exit_code=exit_code,
        success=exit_code == 0,
        duration_ms=1.0,
        stdout=stdout,
        timed_out=timed_out,
    )


@pytest.mark.unit
class TestItAsksTheRightQuestion:
    @pytest.mark.asyncio
    async def test_it_runs_the_standard_anchored_binary_with_json(self) -> None:
        seen: list[list[str]] = []

        async def _exec(
            argv: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            seen.append(argv)
            return _result(_CLEAN, 0)

        await probe_capture(_exec, expectations=_EXPECT)
        assert seen == [EXPORTER_PROBE_COMMAND]
        # --json is now inside the wrapper script rather than a separate argv
        # element: the probe runs the exporter THROUGH the capability's init.sh
        # so it inherits the translated SESSION_STORE_* environment (#852). The
        # prose line the finalizer prints is still not a contract; --json is.
        assert "--json" in seen[0][-1]

    @pytest.mark.asyncio
    async def test_a_clean_probe_is_captured(self) -> None:
        async def _exec(
            _argv: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            return _result(_CLEAN, 0)

        out = await probe_capture(_exec, expectations=_EXPECT)
        assert out.state is CaptureState.CAPTURED
        assert not out.needs_backfill

    @pytest.mark.asyncio
    async def test_no_store_means_nothing_to_ask(self) -> None:
        async def _exec(
            _argv: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            raise AssertionError("must not run the exporter with no store configured")

        out = await probe_capture(_exec, expectations=None)
        assert out.state is CaptureState.DISABLED
        assert not out.needs_backfill


@pytest.mark.unit
class TestNotKnowingIsNeverSuccess:
    @pytest.mark.asyncio
    async def test_an_exec_that_raises_does_not_propagate(self) -> None:
        # This runs during teardown of a phase that may have SUCCEEDED. No
        # exporter problem is worth converting that into a failure.
        async def _exec(
            _argv: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            raise RuntimeError("container already gone")

        out = await probe_capture(_exec, expectations=_EXPECT)
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill
        assert "could not run" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_a_timeout_is_failed(self) -> None:
        # CaptureState.FAILED documents timeout explicitly. Both FAILED and
        # UNKNOWN request backfill, so this is about recording what actually
        # happened rather than changing the recovery.
        async def _exec(
            _argv: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            return _result("", 0, timed_out=True)

        out = await probe_capture(_exec, expectations=_EXPECT, timeout_seconds=5)
        assert out.state is CaptureState.FAILED
        assert out.needs_backfill
        assert "timed out" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_a_timed_out_probe_is_not_read_as_a_clean_sweep(self) -> None:
        # The nastiest shape: a document that WOULD read as success, on a run
        # that did not finish. The timeout has to win.
        async def _exec(
            _argv: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            return _result(_CLEAN, 0, timed_out=True)

        out = await probe_capture(_exec, expectations=_EXPECT)
        assert out.state is CaptureState.FAILED
        assert out.needs_backfill

    @pytest.mark.asyncio
    async def test_a_probe_against_the_wrong_store_is_not_captured(self) -> None:
        async def _exec(
            _argv: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            return _result(_CLEAN, 0)

        out = await probe_capture(
            _exec,
            expectations=CaptureExpectations(
                store_url="http://somewhere-else:9999",
                deployment="syntropic137__dev",
                expect_sessions=True,
            ),
        )
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill


@pytest.mark.unit
class TestTheBoundIsHonoured:
    @pytest.mark.asyncio
    async def test_the_timeout_is_passed_to_the_executor(self) -> None:
        # Teardown is already bounded by the caller; a hung exporter must not
        # extend it. The spool is retained either way, so a missed probe costs
        # a delayed verdict rather than data.
        seen: list[int] = []

        async def _exec(
            _argv: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            seen.append(timeout_seconds)
            return _result(_CLEAN, 0)

        await probe_capture(_exec, expectations=_EXPECT, timeout_seconds=7)
        assert seen == [7]


@pytest.mark.unit
class TestItDoesNotTrustAgentWritableState:
    """The host controls WHO runs the exporter. That is worth nothing if the
    evidence the exporter reads is writable by the thing being audited.

    The capability's own state file lives under the agent-writable spool and
    records which transcripts it believes are already sent. `skipped_unchanged`
    comes from it. An agent that marks an unstored transcript current makes an
    honest exporter report `discovered=1 skipped_unchanged=1` with every loss
    counter at zero, which reads as a clean sweep.
    """

    @pytest.mark.asyncio
    async def test_the_probe_supplies_its_own_state_file(self) -> None:
        seen: list[dict[str, str] | None] = []

        async def _exec(
            _argv: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            seen.append(environment)
            return _result(_CLEAN, 0)

        await probe_capture(_exec, expectations=_EXPECT)
        assert seen and seen[0] is not None
        # Passed under OUR name, not EXPORTER_STATE_FILE. init.sh exports that
        # one itself, pointing into the agent-writable spool, and whichever
        # assignment ran last would win. The wrapper applies the host value
        # after sourcing, which is what keeps this guarantee (#852).
        assert seen[0]["SYN_PROBE_STATE_FILE"] == PROBE_STATE_FILE
        assert "EXPORTER_STATE_FILE" not in seen[0]

    @pytest.mark.asyncio
    async def test_the_probe_state_file_is_outside_the_agent_writable_spool(self) -> None:
        # /tmp is its own tmpfs under the production security profile. The
        # spool is where the agent's transcripts and the capability's state
        # live, and is writable by the agent by design.
        assert not PROBE_STATE_FILE.startswith("/spool")
        assert not PROBE_STATE_FILE.startswith("/workspace")
