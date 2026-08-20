"""The observability lane must not be able to break the run it observes."""

from __future__ import annotations

import asyncio

import pytest

from syn_adapters.workspace_backends.agentic.capture_observation import (
    SESSION_CAPTURE_OBSERVATION,
    build_expectations,
    record_capture_outcome,
)
from syn_adapters.workspace_backends.agentic.capture_result import AuthoritativeCapture
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState
from syn_adapters.workspace_backends.agentic.session_store_env import (
    ENV_AGENTIC_SESSION_STORE_URL,
    build_session_store_env,
    deployment_identity,
)
from syn_shared.settings.session_store import SessionStoreSettings


class _Writer:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[object] = []
        self._fail = fail

    async def record_observation(self, **kwargs: object) -> None:
        """Keyword-only, so the stub does not restate the port's signature.

        Restating it would also reintroduce the wide dict spelling the repo's
        untyped-dict ratchet greps for, and a stub is the wrong place to spend
        that budget.
        """
        if self._fail:
            raise RuntimeError("timescale is down")
        self.calls.append(kwargs)


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
class TestThePhaseToAgentSessionMapping:
    """A phase is host-owned; the agent sessions inside it are many.

    These assert the RECORDED payload, not the in-memory verdict. A mutation
    check found the gap: deleting the writer's assignment entirely left every
    other test green, because the parser tests inspect AuthoritativeCapture and
    the route tests build the payload by hand. Nothing connected the two.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("ids", "expected"),
        [
            (None, None),
            ((), []),
            (("a",), ["a"]),
            (("a", "b"), ["a", "b"]),
        ],
        ids=["not-reported", "confirmed-none", "one", "many"],
    )
    async def test_the_recorded_payload_carries_the_agent_sessions(
        self, ids: tuple[str, ...] | None, expected: list[str] | None
    ) -> None:
        writer = _Writer()
        outcome = AuthoritativeCapture(
            state=CaptureState.CAPTURED,
            store_url="http://store:8799",
            agent_session_ids=ids,
        )

        await record_capture_outcome(
            writer,
            outcome,
            session_id="s-1",
            expectations=None,
            partition="e-1/w-1",
            execution_id="e-1",
            phase_id="p-1",
        )

        data = writer.calls[0]["data"]
        assert data["schema_version"] == 2
        assert data["agent_session_ids"] == expected

    @pytest.mark.asyncio
    async def test_the_payload_survives_a_json_round_trip_into_an_entry(self) -> None:
        """The recorded row is JSON in a store, not a Python object in memory.

        None and [] are the pair most likely to collapse across that boundary,
        and they are exactly the two that must not.
        """
        import json

        from syn_api.routes.capture import _agent_session_ids

        for ids, expected in ((None, None), ((), []), (("a", "b"), ["a", "b"])):
            writer = _Writer()
            await record_capture_outcome(
                writer,
                AuthoritativeCapture(
                    state=CaptureState.CAPTURED,
                    store_url="http://store:8799",
                    agent_session_ids=ids,
                ),
                session_id="s-1",
                expectations=None,
                partition="e-1/w-1",
            )
            stored = json.loads(json.dumps(writer.calls[0]["data"]))
            assert _agent_session_ids(stored) == expected


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
            writer,
            outcome,
            session_id="s-1",
            expectations=None,
            partition="e-1/w-1",
            execution_id="e-1",
            phase_id="p-1",
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
        await record_capture_outcome(
            _Writer(fail=True), outcome, session_id="s-1", expectations=None, partition=None
        )

    @pytest.mark.asyncio
    async def test_no_writer_is_not_an_error(self) -> None:
        outcome = AuthoritativeCapture(state=CaptureState.CAPTURED)
        await record_capture_outcome(
            None, outcome, session_id="s-1", expectations=None, partition=None
        )

    @pytest.mark.asyncio
    async def test_disabled_is_not_recorded(self) -> None:
        # A deployment with no store would otherwise emit one of these per
        # phase forever. Noise trains an operator to ignore the signal, and an
        # indicator nobody reads is worth nothing.
        writer = _Writer()
        outcome = AuthoritativeCapture(state=CaptureState.DISABLED)
        await record_capture_outcome(
            writer, outcome, session_id="s-1", expectations=None, partition=None
        )
        assert writer.calls == []

    @pytest.mark.asyncio
    async def test_captured_IS_recorded(self) -> None:
        # Only DISABLED is suppressed. A successful capture is the baseline an
        # operator compares against, so omitting it would make absence
        # ambiguous.
        writer = _Writer()
        outcome = AuthoritativeCapture(state=CaptureState.CAPTURED)
        await record_capture_outcome(
            writer, outcome, session_id="s-1", expectations=None, partition=None
        )
        assert len(writer.calls) == 1


@pytest.mark.unit
class TestExpectationsMatchWhatTheContainerActuallyGets:
    """The two sides must agree VALUE for value, not merely come from one source.

    build_expectations derives the destination from settings, and
    session_store_env injects it into the container. If those derivations
    differ at all, every verdict compares unequal and reads UNKNOWN: an
    indicator uniformly broken while appearing to work.

    A whitespace-padded URL is the concrete case. The settings validator
    rejects a whitespace-ONLY value but does not trim a valid one, and the
    injector applies .strip(). Without the same call here, the two disagree
    forever.
    """

    def test_a_padded_url_still_matches_what_is_injected(self) -> None:
        settings = SessionStoreSettings(url="  http://store:8799  ")
        expect = build_expectations(settings, "dev", expect_sessions=True)
        env = build_session_store_env(
            settings,
            execution_id="e-1",
            workspace_id="w-1",
            deployment=deployment_identity("dev"),
        )
        assert expect is not None
        assert expect.store_url == env[ENV_AGENTIC_SESSION_STORE_URL]

    def test_the_ordinary_case_matches_too(self) -> None:
        settings = SessionStoreSettings(url="http://store:8799")
        expect = build_expectations(settings, "dev", expect_sessions=True)
        env = build_session_store_env(
            settings,
            execution_id="e-1",
            workspace_id="w-1",
            deployment=deployment_identity("dev"),
        )
        assert expect is not None
        assert expect.store_url == env[ENV_AGENTIC_SESSION_STORE_URL]


@pytest.mark.unit
class TestTelemetryCannotStallTeardown:
    @pytest.mark.asyncio
    async def test_a_hanging_write_is_bounded(self) -> None:
        # An unbounded await on a hung connection pool would block a phase that
        # has already finished its actual work.
        class _Hangs:
            async def record_observation(self, **_kwargs: object) -> None:
                await asyncio.sleep(3600)

        outcome = AuthoritativeCapture(state=CaptureState.CAPTURED)
        await asyncio.wait_for(
            record_capture_outcome(
                _Hangs(),  # type: ignore[arg-type]
                outcome,
                session_id="s-1",
                expectations=None,
                partition=None,
            ),
            timeout=10,
        )

    @pytest.mark.asyncio
    async def test_external_cancellation_still_propagates(self) -> None:
        # Swallowing cancellation during teardown hangs shutdown, which is
        # worse than losing a telemetry record.
        class _Cancels:
            async def record_observation(self, **_kwargs: object) -> None:
                raise asyncio.CancelledError

        outcome = AuthoritativeCapture(state=CaptureState.CAPTURED)
        with pytest.raises(asyncio.CancelledError):
            await record_capture_outcome(
                _Cancels(),  # type: ignore[arg-type]
                outcome,
                session_id="s-1",
                expectations=None,
                partition=None,
            )
