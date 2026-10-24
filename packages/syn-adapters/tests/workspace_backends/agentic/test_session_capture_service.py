"""The assembled capture step, and the one rule that outranks correctness here.

Capture is fail-open. A transcript that did not reach the store must never turn
an hour of successful agent work into a failed phase. Every other property in
this file is subordinate to that: the service returns a verdict, it does not
raise one.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from syn_adapters.workspace_backends.agentic.capability_start import StartCapability
from syn_adapters.workspace_backends.agentic.capture_observation import (
    read_capture_status_display,
)
from syn_adapters.workspace_backends.agentic.capture_result import AuthoritativeCapture
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState
from syn_adapters.workspace_backends.agentic.session_capture_service import (
    SessionCaptureService,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_shared.settings.session_store import SessionStoreSettings

_STORE = "http://store:8799"

_CLEAN = json.dumps(
    {
        "schema_version": 1,
        "captured_everything": True,
        "store_url": _STORE,
        "origin": {"environment": "container", "deployment": "syntropic137__dev"},
        "counters": {"discovered": 1, "uploaded": 1, "accepted": 1},
    }
)


class _Writer:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[object] = []
        self._fail = fail

    async def record_observation(self, **kwargs: object) -> None:
        if self._fail:
            raise RuntimeError("timescale is down")
        self.calls.append(kwargs)


def _ok_exec(stdout: str, exit_code: int = 0):
    async def _exec(
        _command: list[str], *, timeout_seconds: int, environment=None
    ) -> ExecutionResult:
        return ExecutionResult(
            exit_code=exit_code,
            success=exit_code == 0,
            duration_ms=1.0,
            stdout=stdout,
        )

    return _exec


class _NoStatus:
    """No capability_status row: the pre-#1516 behaviour, kept for these tests."""

    async def read(self, execute: object, capability: str) -> None:
        return None


def _service(writer: _Writer | None, url: str | None = _STORE) -> SessionCaptureService:
    return SessionCaptureService(
        SessionStoreSettings(url=url), "dev", writer, capability_reader=_NoStatus()
    )


@pytest.mark.unit
class TestItRecordsWhatItFound:
    @pytest.mark.asyncio
    async def test_a_clean_capture_is_recorded_with_its_partition(self) -> None:
        writer = _Writer()
        outcome = await _service(writer).capture_and_record(
            _ok_exec(_CLEAN),
            session_id="s-1",
            execution_id="e-1",
            workspace_id="w-1",
            phase_id="p-1",
            expect_sessions=True,
        )
        assert outcome.state is CaptureState.CAPTURED
        assert len(writer.calls) == 1
        call = writer.calls[0]
        assert isinstance(call, dict)
        data = call["data"]
        assert isinstance(data, dict)
        # The identity a retry needs to find the transcripts again, matching
        # what the capability was told to spool into.
        assert data["partition"] == "e-1/w-1"
        assert data["expected_store_url"] == _STORE

    @pytest.mark.asyncio
    async def test_a_disabled_store_records_nothing_and_runs_no_exporter(self) -> None:
        writer = _Writer()

        async def _must_not_run(*_a: object, **_k: object) -> ExecutionResult:
            raise AssertionError("no store configured; nothing to ask")

        outcome = await _service(writer, url=None).capture_and_record(
            _must_not_run,
            session_id="s-1",
            execution_id="e-1",
            workspace_id="w-1",
            phase_id="p-1",
            expect_sessions=True,
        )
        assert outcome.state is CaptureState.DISABLED
        assert writer.calls == []


@pytest.mark.unit
class TestNothingHereCanFailAPhase:
    @pytest.mark.asyncio
    async def test_an_exporter_that_explodes_returns_a_verdict(self) -> None:
        async def _boom(*_a: object, **_k: object) -> ExecutionResult:
            raise RuntimeError("container already gone")

        writer = _Writer()
        outcome = await _service(writer).capture_and_record(
            _boom,
            session_id="s-1",
            execution_id="e-1",
            workspace_id="w-1",
            phase_id="p-1",
            expect_sessions=True,
        )
        assert outcome.state is CaptureState.UNKNOWN
        assert outcome.needs_backfill
        # Still recorded: an unanswerable probe is exactly what a backfill
        # pass needs to know about.
        assert len(writer.calls) == 1

    @pytest.mark.asyncio
    async def test_a_writer_that_explodes_still_returns_the_verdict(self) -> None:
        outcome = await _service(_Writer(fail=True)).capture_and_record(
            _ok_exec(_CLEAN),
            session_id="s-1",
            execution_id="e-1",
            workspace_id="w-1",
            phase_id="p-1",
            expect_sessions=True,
        )
        assert outcome.state is CaptureState.CAPTURED

    @pytest.mark.asyncio
    async def test_no_writer_at_all_is_not_an_error(self) -> None:
        outcome = await _service(None).capture_and_record(
            _ok_exec(_CLEAN),
            session_id="s-1",
            execution_id="e-1",
            workspace_id="w-1",
            phase_id="p-1",
            expect_sessions=True,
        )
        assert outcome.state is CaptureState.CAPTURED

    @pytest.mark.asyncio
    async def test_cancellation_still_propagates(self) -> None:
        # Swallowing cancellation during teardown hangs shutdown, which is
        # worse than losing a verdict.
        async def _cancel(*_a: object, **_k: object) -> ExecutionResult:
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await _service(_Writer()).capture_and_record(
                _cancel,
                session_id="s-1",
                execution_id="e-1",
                workspace_id="w-1",
                phase_id="p-1",
                expect_sessions=True,
            )


@pytest.mark.unit
class TestExpectSessionsReachesTheVerdict:
    @pytest.mark.asyncio
    async def test_an_empty_sweep_is_unknown_when_a_session_was_expected(self) -> None:
        # The deleted-spool case, end to end through the service.
        empty = json.dumps(
            {
                "schema_version": 1,
                "captured_everything": True,
                "store_url": _STORE,
                "origin": {"environment": "container", "deployment": "syntropic137__dev"},
                "counters": {"discovered": 0, "uploaded": 0, "accepted": 0},
            }
        )
        outcome = await _service(_Writer()).capture_and_record(
            _ok_exec(empty),
            session_id="s-1",
            execution_id="e-1",
            workspace_id="w-1",
            phase_id="p-1",
            expect_sessions=True,
        )
        assert outcome.state is CaptureState.UNKNOWN
        assert outcome.needs_backfill


@pytest.mark.unit
class TestUnprovisionedWorkspacesAreNotProbed:
    """A configured store is not the same as a workspace that received one.

    Only the agentic backend injects the session-store environment, and only
    images carrying the exporter can act on it. That is derived by ASKING the
    workspace, never by trusting a caller-supplied flag.
    """

    @pytest.mark.asyncio
    async def test_a_provisioning_failure_is_failed_and_asks_for_backfill(self) -> None:
        """An exporter that IS present but unconfigured is a real failure.

        This document is copied from a real run of the pinned omni image with
        no SESSION_STORE_URL in its environment, so the shape under test is the
        one the binary actually emits rather than one invented to pass.
        """
        writer = _Writer()

        unconfigured = _ok_exec(
            json.dumps(
                {
                    "schema_version": 1,
                    "scs_version": "1.0",
                    "captured_everything": False,
                    "error": "missing required env var SESSION_STORE_URL",
                    "store_url": None,
                    "origin": None,
                }
            ),
            exit_code=1,
        )

        outcome = await _service(writer).capture_and_record(
            unconfigured,
            session_id="s-1",
            execution_id="e-1",
            workspace_id="w-1",
            phase_id="p-1",
            expect_sessions=True,
        )
        # FAILED, not DISABLED. The binary is baked in, so this workspace was
        # meant to capture and its injection broke. Calling that "off" would
        # silently discard transcripts that really are sitting in the spool.
        # Absence of the capability is detected by the binary being ABSENT,
        # which is the test below, not by an unconfigured one being present.
        assert outcome.state is CaptureState.FAILED
        assert outcome.needs_backfill
        assert len(writer.calls) == 1

    @pytest.mark.asyncio
    async def test_an_image_without_the_exporter_is_disabled(self) -> None:
        """127 is the shell reporting that the binary is not there."""
        writer = _Writer()

        outcome = await _service(writer).capture_and_record(
            _ok_exec("", exit_code=127),
            session_id="s-1",
            execution_id="e-1",
            workspace_id="w-1",
            phase_id="p-1",
            expect_sessions=True,
        )
        assert outcome.state is CaptureState.DISABLED
        assert not outcome.needs_backfill


class _Start:
    """A workspace whose entrypoint recorded ``start`` for the session store."""

    def __init__(self, start: StartCapability | None) -> None:
        self.start = start
        self.asked: list[str] = []

    async def read(self, execute: object, capability: str) -> StartCapability | None:
        self.asked.append(capability)
        return self.start


_DEGRADED = StartCapability(
    capability="session-store",
    status="degraded",
    failed_checks=("store_reachable", "auth_accepted"),
    doctor_exit=3,
)


def _service_with(start: _Start, writer: _Writer, url: str | None = _STORE) -> SessionCaptureService:
    return SessionCaptureService(
        SessionStoreSettings(url=url), "dev", writer, capability_reader=start
    )


async def _capture(service: SessionCaptureService, execute) -> AuthoritativeCapture:
    return await service.capture_and_record(
        execute,
        session_id="s-1",
        execution_id="e-1",
        workspace_id="w-1",
        phase_id="p-1",
        expect_sessions=True,
    )


@pytest.mark.unit
class TestADegradedStartReadsAsDegraded:
    """#1516: a capture loss after a degraded start is explained, not unexplained."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exporter",
        [
            pytest.param(_ok_exec("", exit_code=1), id="exporter-failed"),
            # 127 alone would read as DISABLED and record NOTHING: the
            # degraded run would vanish from the indicator entirely.
            pytest.param(_ok_exec("", exit_code=127), id="exporter-absent"),
        ],
    )
    async def test_the_recorded_verdict_names_the_failed_checks(self, exporter) -> None:
        writer = _Writer()

        outcome = await _capture(_service_with(_Start(_DEGRADED), writer), exporter)

        assert outcome.state is CaptureState.DEGRADED
        assert outcome.needs_backfill
        assert len(writer.calls) == 1
        payload = writer.calls[0]["data"]
        assert isinstance(payload, dict)
        assert payload["state"] == "degraded"
        # The consumer of the payload, not the payload: what the API serves.
        assert (
            read_capture_status_display(payload)
            == "Capture degraded: store_reachable, auth_accepted failed"
        )

    @pytest.mark.asyncio
    async def test_a_ready_start_changes_nothing(self) -> None:
        writer = _Writer()
        ready = StartCapability(capability="session-store", status="ready")

        outcome = await _capture(_service_with(_Start(ready), writer), _ok_exec(_CLEAN))

        assert outcome.state is CaptureState.CAPTURED
        payload = writer.calls[0]["data"]
        assert isinstance(payload, dict)
        assert read_capture_status_display(payload) is None

    @pytest.mark.asyncio
    async def test_a_session_the_exporter_stored_is_still_captured(self) -> None:
        """Host-side evidence of a stored session outranks the start prediction."""
        writer = _Writer()

        outcome = await _capture(_service_with(_Start(_DEGRADED), writer), _ok_exec(_CLEAN))

        assert outcome.state is CaptureState.CAPTURED

    @pytest.mark.asyncio
    async def test_no_store_configured_asks_nothing_and_shows_nothing(self) -> None:
        writer = _Writer()
        start = _Start(_DEGRADED)

        outcome = await _capture(_service_with(start, writer, url=None), _ok_exec(""))

        assert outcome.state is CaptureState.DISABLED
        assert start.asked == []
        assert writer.calls == []
