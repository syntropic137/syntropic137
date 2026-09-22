"""Replay-safe evidence derived from existing platform registration events."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.events.SessionInvocationRecordedEvent import (
    SessionInvocationRecordedEvent,
)
from syn_domain.contexts.agent_sessions.domain.events.SessionStartedEvent import SessionStartedEvent
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    LineageEvidence,
    MembershipEvidence,
    NodeEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceClass,
    EvidenceReference,
    InventoryNodeRef,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.ports.SessionCaptureSpoolPort import CaptureSpool
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import EvidenceBatch

from .invocation_evidence import invocation_evidence

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.agent_sessions.ports.SessionCaptureSpoolPort import (
        SessionCaptureSpoolPort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceWritePort,
    )


class HostSessionEvidenceProjector:
    """Projects durable facts only; never launches work or fetches transcripts.

    Historical sessions remain platform nodes. A SessionStarted event does not
    prove a native invocation, capture completeness, or a native parent ID.
    """

    def __init__(
        self,
        evidence: SessionEvidenceWritePort,
        source_instance_id: str,
        spools: SessionCaptureSpoolPort | None = None,
    ) -> None:
        self._evidence = evidence
        self._source = source_instance_id
        self._spools = spools

    def get_subscribed_event_types(self) -> set[str]:
        return {SessionStartedEvent.event_type, SessionInvocationRecordedEvent.event_type}

    async def handle(self, envelope: EventEnvelope[DomainEvent]) -> None:
        if envelope.metadata.event_type == SessionInvocationRecordedEvent.event_type:
            await self._project_invocation(envelope)
            return
        if envelope.metadata.event_type != SessionStartedEvent.event_type:
            return
        event = SessionStartedEvent.model_validate_json(envelope.event.model_dump_json())
        if not event.execution_id:
            return  # Old unscoped sessions cannot be assigned to a run by guesswork.
        run = RunIdentity(source_instance_id=self._source, execution_id=event.execution_id)
        if self._spools is not None and event.capture_profile == "local-spool/1":
            await self._spools.project(
                CaptureSpool(run=run, session_id=event.session_id, phase_id=event.phase_id)
            )
        node = InventoryNodeRef(
            kind="platform", source_instance_id=self._source, local_id=event.session_id
        )
        reference = EvidenceReference(
            producer_id="syntropic-session-events",
            evidence_id=envelope.metadata.event_id,
            source_revision=str(envelope.metadata.aggregate_nonce),
            locator=f"AgentSession-{envelope.metadata.aggregate_id}",
            extractor_version="host-session-events/1",
        )
        edges: tuple[LineageEvidence, ...] = ()
        if event.parent_session_id:
            edges = (
                LineageEvidence(
                    parent=InventoryNodeRef(
                        kind="platform",
                        source_instance_id=self._source,
                        local_id=event.parent_session_id,
                    ),
                    child=node,
                    relation="spawn",
                    confidence=EvidenceClass.REGISTERED,
                    evidence=reference,
                ),
            )
        await self._evidence.append(
            EvidenceBatch(
                batch_id=envelope.metadata.event_id,
                producer_id=reference.producer_id,
                evidence=SessionEvidence(
                    run=run,
                    nodes=(NodeEvidence(node=node, evidence=reference),),
                    memberships=(
                        MembershipEvidence(
                            node=node,
                            run=run,
                            phase_id=event.phase_id or None,
                            confidence=EvidenceClass.REGISTERED,
                            evidence=reference,
                        ),
                    ),
                    edges=edges,
                ),
            )
        )

    async def _project_invocation(self, envelope: EventEnvelope[DomainEvent]) -> None:
        event = SessionInvocationRecordedEvent.model_validate_json(envelope.event.model_dump_json())
        reference = EvidenceReference(
            producer_id="syntropic-invocation-events",
            evidence_id=envelope.metadata.event_id,
            source_revision=str(envelope.metadata.aggregate_nonce),
            locator=f"AgentSession-{envelope.metadata.aggregate_id}",
            extractor_version="host-invocation-events/1",
        )
        await self._evidence.append(
            EvidenceBatch(
                batch_id=envelope.metadata.event_id,
                producer_id=reference.producer_id,
                evidence=invocation_evidence(event, self._source, reference),
            )
        )
