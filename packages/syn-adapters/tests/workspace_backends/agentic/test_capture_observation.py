"""The observability lane must not be able to break the run it observes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

from syn_adapters.workspace_backends.agentic.capture_observation import (
    SESSION_CAPTURE_OBSERVATION,
    build_expectations,
    record_capture_outcome,
)
from syn_adapters.workspace_backends.agentic.capture_result import AuthoritativeCapture
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState
from syn_shared.settings.session_store import SessionStoreSettings


class _Writer:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[Mapping[str, object]] = []
        self._fail = fail

    async def record_observation(
        self,
        session_id: str,
        observation_type: str,
        data: Mapping[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        if self._fail:
            raise RuntimeError("timescale is down")
        self.calls.append(
            {
                "session_id": session_id,
                "observation_type": observation_type,
                "data": data,
                "execution_id": execution_id,
            }
        )


@pytest.mark.unit
class TestExpectationsComeFromTheSameSettings:
    def test_no_store_means_no_expectations(self) -> None:
        # None rather than an empty expectation, so "capture is off" stays
        # distinguishable from "capture ran and told us nothing".
        settings = SessionStoreSettings(url=None)
        assert build_expectations(settings, "dev", expect_sessions=True) is None

    def test_expectations_carry_the_configured_store_and_deployment(self) -> None:
        settings = SessionStoreSettings(url="http://store:8799")
        expect = build_expectations(settings, "dev", expect_sessions=True)
        assert expect is not None
        assert expect.store_url == "http://store:8799"
        assert expect.deployment == "syntropic137__dev"
        assert expect.expect_sessions is True

    def test_expect_sessions_is_the_callers_to_state(self) -> None:
        # Only the caller knows whether an agent actually ran, and that is what
        # stops a deleted spool reading as a clean sweep.
        settings = SessionStoreSettings(url="http://store:8799")
        expect = build_expectations(settings, "dev", expect_sessions=False)
        assert expect is not None
        assert expect.expect_sessions is False


@pytest.mark.unit
class TestRecordingIsLaneTwo:
    @pytest.mark.asyncio
    async def test_a_verdict_is_written_with_its_identity(self) -> None:
        writer = _Writer()
        outcome = AuthoritativeCapture(
            state=CaptureState.INCOMPLETE,
            reason="sweep incomplete (rejected=1)",
            store_url="http://store:8799",
            counters={"discovered": 1, "rejected": 1},
        )
        await record_capture_outcome(
            writer, outcome, session_id="s-1", execution_id="e-1", phase_id="p-1"
        )
        assert len(writer.calls) == 1
        call = writer.calls[0]
        assert call["observation_type"] == SESSION_CAPTURE_OBSERVATION
        assert call["session_id"] == "s-1"
        data = call["data"]
        assert isinstance(data, dict)
        assert data["state"] == "incomplete"
        assert data["needs_backfill"] is True
        assert data["counters"] == {"discovered": 1, "rejected": 1}

    @pytest.mark.asyncio
    async def test_a_writer_that_raises_does_not_fail_the_phase(self) -> None:
        # Losing the record is bad. Converting a successful phase into a failed
        # one because telemetry could not be written is worse, and would
        # reverse the fail-open policy by the back door.
        outcome = AuthoritativeCapture(state=CaptureState.CAPTURED)
        await record_capture_outcome(_Writer(fail=True), outcome, session_id="s-1")

    @pytest.mark.asyncio
    async def test_no_writer_is_not_an_error(self) -> None:
        outcome = AuthoritativeCapture(state=CaptureState.CAPTURED)
        await record_capture_outcome(None, outcome, session_id="s-1")

    @pytest.mark.asyncio
    async def test_disabled_is_not_recorded(self) -> None:
        # A deployment with no store would otherwise emit one of these per
        # phase forever. Noise trains an operator to ignore the signal, and an
        # indicator nobody reads is worth nothing.
        writer = _Writer()
        outcome = AuthoritativeCapture(state=CaptureState.DISABLED)
        await record_capture_outcome(writer, outcome, session_id="s-1")
        assert writer.calls == []

    @pytest.mark.asyncio
    async def test_captured_IS_recorded(self) -> None:
        # Only DISABLED is suppressed. A successful capture is the baseline an
        # operator compares against, so omitting it would make absence
        # ambiguous.
        writer = _Writer()
        outcome = AuthoritativeCapture(state=CaptureState.CAPTURED)
        await record_capture_outcome(writer, outcome, session_id="s-1")
        assert len(writer.calls) == 1
