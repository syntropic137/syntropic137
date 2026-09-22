"""Historical platform facts retain exact scope and never fabricate native work."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from event_sourcing import EventEnvelope, EventMetadata

from syn_domain.contexts.agent_sessions import HostSessionEvidenceProjector
from syn_domain.contexts.agent_sessions.domain.events.SessionStartedEvent import SessionStartedEvent
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import EvidenceBatch

pytestmark = pytest.mark.unit


def _event(
    *, execution_id: str | None, parent: str | None = None
) -> EventEnvelope[SessionStartedEvent]:
    return EventEnvelope(
        event=SessionStartedEvent(
            session_id="child",
            workflow_id="definition",
            execution_id=execution_id,
            phase_id="phase",
            parent_session_id=parent,
            agent_provider="fake",
            started_at=datetime.now(UTC),
        ),
        metadata=EventMetadata(
            event_id="registration",
            aggregate_id="child",
            aggregate_type="AgentSession",
            aggregate_nonce=1,
            global_nonce=17,
            event_type=SessionStartedEvent.event_type,
        ),
    )


async def test_replay_uses_same_evidence_and_only_explicit_platform_parent() -> None:
    journal = AsyncMock()
    projector = HostSessionEvidenceProjector(journal, "installation")
    event = _event(execution_id="run", parent="parent")
    await projector.handle(event)
    await projector.handle(event)
    first = journal.append.await_args_list[0].args[0]
    second = journal.append.await_args_list[1].args[0]
    assert isinstance(first, EvidenceBatch)
    assert first == second
    assert first.batch_id == "registration"
    assert first.evidence.run.execution_id == "run"
    assert first.evidence.memberships[0].phase_id == "phase"
    assert first.evidence.edges[0].parent.local_id == "parent"
    assert first.evidence.edges[0].parent.kind == "platform"
    assert first.evidence.coverage_contract is None
    assert first.evidence.bindings == ()
    assert first.evidence.captures == ()


async def test_unscoped_history_is_not_assigned_using_workflow_definition() -> None:
    journal = AsyncMock()
    await HostSessionEvidenceProjector(journal, "installation").handle(_event(execution_id=None))
    journal.append.assert_not_awaited()


async def test_root_history_has_no_guessed_parent() -> None:
    journal = AsyncMock()
    await HostSessionEvidenceProjector(journal, "installation").handle(_event(execution_id="run"))
    batch = journal.append.await_args.args[0]
    assert isinstance(batch, EvidenceBatch)
    assert batch.evidence.edges == ()


async def test_only_explicit_capture_intent_projects_recovery_work() -> None:
    spools = AsyncMock()
    projector = HostSessionEvidenceProjector(AsyncMock(), "installation", spools)
    historical = _event(execution_id="run")
    await projector.handle(historical)
    spools.project.assert_not_awaited()
    current = historical.model_copy(
        update={"event": historical.event.model_copy(update={"capture_profile": "local-spool/1"})}
    )
    await projector.handle(current)
    await projector.handle(current)
    assert spools.project.await_args_list[0] == spools.project.await_args_list[1]
    assert spools.project.await_args.args[0].run.execution_id == "run"
    assert spools.project.await_args.args[0].session_id == "child"
