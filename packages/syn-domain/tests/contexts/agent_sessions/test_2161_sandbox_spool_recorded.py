"""The AgentSession records where its sandbox spool lives, once (#2161)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from syn_domain.contexts.agent_sessions import (
    AgentSessionAggregate,
    CompleteSessionCommand,
    HostSessionEvidenceProjector,
    RecordSandboxSpoolCommand,
    SandboxSpoolRecordedEvent,
    StartSessionCommand,
)

pytestmark = pytest.mark.unit


def _session(capture_profile: str | None = "sandbox-spool/1") -> AgentSessionAggregate:
    session = AgentSessionAggregate()
    session.start_session(
        StartSessionCommand(
            aggregate_id="s-2161",
            workflow_id="wf",
            execution_id="exec-2161",
            capture_profile=capture_profile,
            phase_id="implement",
            agent_provider="claude",
        )
    )
    return session


def _record(sandbox_id: str = "sbx-1") -> RecordSandboxSpoolCommand:
    return RecordSandboxSpoolCommand(
        aggregate_id="s-2161", backend="e2b", executor_id="host-a.0123", sandbox_id=sandbox_id
    )


def _recorded(session: AgentSessionAggregate) -> list[SandboxSpoolRecordedEvent]:
    return [
        e.event
        for e in session.get_uncommitted_events()
        if isinstance(e.event, SandboxSpoolRecordedEvent)
    ]


def test_a_sandbox_spool_session_records_its_sandbox_with_the_session_scope() -> None:
    session = _session()
    session.record_sandbox_spool(_record())
    (event,) = _recorded(session)
    assert (event.session_id, event.execution_id, event.phase_id) == (
        "s-2161",
        "exec-2161",
        "implement",
    )
    assert (event.backend, event.executor_id, event.sandbox_id) == ("e2b", "host-a.0123", "sbx-1")


def test_recording_the_same_sandbox_again_changes_nothing() -> None:
    session = _session()
    session.record_sandbox_spool(_record())
    session.record_sandbox_spool(_record())
    assert len(_recorded(session)) == 1


def test_a_second_sandbox_for_one_session_is_refused() -> None:
    session = _session()
    session.record_sandbox_spool(_record())
    with pytest.raises(ValueError, match="another sandbox"):
        session.record_sandbox_spool(_record("sbx-2"))


def test_the_recorded_sandbox_survives_replay() -> None:
    """A rehydrated session knows its sandbox, so a re-dispatch is still a no-op."""
    origin = _session()
    origin.record_sandbox_spool(_record())
    stream = origin.get_uncommitted_events()
    replayed = AgentSessionAggregate()
    replayed.rehydrate(stream)
    replayed.record_sandbox_spool(_record())
    assert replayed.get_uncommitted_events() == []
    with pytest.raises(ValueError, match="another sandbox"):
        replayed.record_sandbox_spool(_record("sbx-2"))


@pytest.mark.parametrize("profile", ["local-spool/1", None])
def test_a_docker_or_historical_session_has_no_sandbox_spool(profile: str | None) -> None:
    session = _session(profile)
    with pytest.raises(ValueError, match="sandbox-spool/1"):
        session.record_sandbox_spool(_record())


def test_a_finished_session_records_no_sandbox() -> None:
    session = _session()
    session.complete_session(CompleteSessionCommand(aggregate_id="s-2161", success=True))
    with pytest.raises(ValueError, match="not running"):
        session.record_sandbox_spool(_record())


def test_historical_streams_still_replay() -> None:
    """Streams written before #2161 carry no capture profile and no new event."""
    origin = _session(None)
    origin.complete_session(CompleteSessionCommand(aggregate_id="s-2161", success=False))
    replayed = AgentSessionAggregate()
    replayed.rehydrate(origin.get_uncommitted_events())
    assert replayed.execution_id == "exec-2161"


def test_the_event_is_frozen_and_refuses_a_reattach_token() -> None:
    fields = {
        "session_id": "s",
        "execution_id": "e",
        "phase_id": "p",
        "backend": "e2b",
        "executor_id": "host",
        "sandbox_id": "sbx",
        "recorded_at": datetime.now(UTC),
    }
    event = SandboxSpoolRecordedEvent(**fields)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        event.sandbox_id = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        SandboxSpoolRecordedEvent(**fields, reattach_token="not-a-real-token")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RecordSandboxSpoolCommand(
            aggregate_id="s",
            backend="e2b",
            executor_id="host",
            sandbox_id="sbx",
            reattach_token="not-a-real-token",  # type: ignore[call-arg]
        )


def test_docker_is_not_a_sandbox_backend() -> None:
    with pytest.raises(ValidationError):
        RecordSandboxSpoolCommand(
            aggregate_id="s",
            backend="docker",  # type: ignore[arg-type]
            executor_id="host",
            sandbox_id="sbx",
        )


def test_the_event_is_subscribed_only_with_a_spool_port() -> None:
    from unittest.mock import AsyncMock

    assert SandboxSpoolRecordedEvent.event_type not in (
        HostSessionEvidenceProjector(AsyncMock(), "i").get_subscribed_event_types()
    )
    assert SandboxSpoolRecordedEvent.event_type in (
        HostSessionEvidenceProjector(AsyncMock(), "i", AsyncMock()).get_subscribed_event_types()
    )
