"""Replay-safe evidence derived from existing platform registration events."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.events.InventoryReconciliationSweepEvent import (
    InventoryReconciliationSweepEvent,
)
from syn_domain.contexts.agent_sessions.domain.events.SessionInvocationRecordedEvent import (
    SessionInvocationRecordedEvent,
)
from syn_domain.contexts.agent_sessions.domain.events.SessionStartedEvent import SessionStartedEvent
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    InvocationLifecycleEvidence,
    LineageEvidence,
    MembershipEvidence,
    NodeEvidence,
    RunSettlementStage,
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
from syn_domain.contexts.agent_sessions.ports.SessionSettlementPort import SettlementDeadline

from .execution_settlement import (
    DEADLINE_BATCH,
    SETTLEMENT_PRODUCER,
    ExecutionTerminal,
    ExecutionTerminalEventType,
    settlement_batch,
)
from .invocation_evidence import invocation_evidence

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.agent_sessions.ports.SessionCaptureSpoolPort import (
        SessionCaptureSpoolPort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceWritePort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionSettlementPort import (
        SessionSettlementPort,
    )

# Deadlines released per clock observation; the rest follow on later ticks.
_DEADLINES_PER_SWEEP = 100
_TERMINAL_EVENT_TYPES = frozenset(ExecutionTerminalEventType)


class HostSessionEvidenceProjector:
    """Projects durable facts only; never launches work or fetches transcripts.

    Historical sessions remain platform nodes. A SessionStarted event does not
    prove a native invocation, capture completeness, or a native parent ID.

    Settlement: a terminal execution appends an EXECUTION_TERMINAL fact and
    schedules one durable deadline ``settlement_grace`` after the event's own
    timestamp. A recorded clock observation at or past it appends the
    SETTLEMENT_DEADLINE fact. Both derive from recorded events only, so replay
    reproduces the same batches; the resolver decides the seal from them.
    """

    def __init__(
        self,
        evidence: SessionEvidenceWritePort,
        source_instance_id: str,
        spools: SessionCaptureSpoolPort | None = None,
        *,
        settlements: SessionSettlementPort | None = None,
        settlement_grace: timedelta = timedelta(minutes=30),
    ) -> None:
        if settlement_grace < timedelta(0):
            raise ValueError("settlement grace cannot be negative")
        self._evidence = evidence
        self._source = source_instance_id
        self._spools = spools
        self._settlements = settlements
        self._grace = settlement_grace

    def get_subscribed_event_types(self) -> set[str]:
        types = {
            SessionStartedEvent.event_type,
            SessionInvocationRecordedEvent.event_type,
            *ExecutionTerminalEventType,
        }
        if self._settlements is not None:
            types.add(InventoryReconciliationSweepEvent.event_type)
        return types

    async def handle(self, envelope: EventEnvelope[DomainEvent]) -> None:
        event_type = envelope.metadata.event_type
        if event_type == SessionInvocationRecordedEvent.event_type:
            await self._project_invocation(envelope)
            return
        if event_type in _TERMINAL_EVENT_TYPES:
            await self._project_terminal(envelope)
            return
        if event_type == InventoryReconciliationSweepEvent.event_type:
            await self._release_deadlines(envelope)
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

        if event.status == "registered":
            return
        # Separate stream leaves every historical identity batch byte-equivalent.
        producer = "syntropic-invocation-lifecycle"
        lifecycle_reference = reference.model_copy(
            update={
                "producer_id": producer,
                "extractor_version": "host-invocation-lifecycle/1",
            }
        )
        await self._evidence.append(
            EvidenceBatch(
                batch_id=envelope.metadata.event_id,
                producer_id=producer,
                evidence=SessionEvidence(
                    run=RunIdentity(
                        source_instance_id=self._source, execution_id=event.execution_id
                    ),
                    invocation_lifecycle=(
                        InvocationLifecycleEvidence(
                            node=InventoryNodeRef(
                                kind="invocation",
                                source_instance_id=self._source,
                                local_id=event.invocation_id,
                            ),
                            sequence=envelope.metadata.aggregate_nonce + 1,
                            status=event.status,
                            evidence=lifecycle_reference,
                        ),
                    ),
                ),
            )
        )

    async def _project_terminal(self, envelope: EventEnvelope[DomainEvent]) -> None:
        event = ExecutionTerminal.model_validate_json(envelope.event.model_dump_json())
        if not event.execution_id:
            return
        metadata = envelope.metadata
        run = RunIdentity(source_instance_id=self._source, execution_id=event.execution_id)
        reference = EvidenceReference(
            producer_id=SETTLEMENT_PRODUCER,
            evidence_id=metadata.event_id,
            source_revision=str(metadata.aggregate_nonce),
            locator=f"{metadata.aggregate_type}-{metadata.aggregate_id}",
            extractor_version="host-execution-settlement/1",
        )
        due_at = None
        if self._settlements is not None:
            # First terminal fact per run fixes the deadline durably. Replay
            # reads that record back, so changing the grace setting later
            # never changes an existing run's facts or revisions.
            fixed = await self._settlements.schedule(
                SettlementDeadline(
                    run=run, due_at=metadata.timestamp + self._grace, terminal=reference
                )
            )
            due_at = fixed.due_at
        await self._evidence.append(
            settlement_batch(
                run,
                reference,
                RunSettlementStage.EXECUTION_TERMINAL,
                f"terminal:{metadata.event_id}",
                due_at,
            )
        )

    async def _release_deadlines(self, envelope: EventEnvelope[DomainEvent]) -> None:
        if self._settlements is None:
            return
        sweep = InventoryReconciliationSweepEvent.model_validate_json(
            envelope.event.model_dump_json()
        )
        page = await self._settlements.due(sweep.observed_at, limit=_DEADLINES_PER_SWEEP)
        for deadline in page.items:
            if deadline.run.source_instance_id != self._source:
                raise ValueError("settlement deadline belongs to another installation")
            # Durable fact first; a crash before settle() re-appends identically.
            await self._evidence.append(
                settlement_batch(
                    deadline.run,
                    deadline.terminal,
                    RunSettlementStage.SETTLEMENT_DEADLINE,
                    DEADLINE_BATCH,
                    deadline.due_at,
                )
            )
            await self._settlements.settle(deadline)
