"""Replay-safe evidence derived from existing platform registration events."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.events.InventoryReconciliationSweepEvent import (
    InventoryReconciliationSweepEvent,
)
from syn_domain.contexts.agent_sessions.domain.events.SessionInvocationBindingConflictedEvent import (
    SessionInvocationBindingConflictedEvent,
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
from .invocation_evidence import binding_conflict_evidence, invocation_evidence

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
    durably fixes one deadline ``settlement_grace`` after the event's own
    timestamp (first terminal fact wins). A clock event only records its
    observed time. ``release_deadlines()`` runs from the process manager's
    live ``process_pending()`` and appends SETTLEMENT_DEADLINE facts for
    deadlines at or before the latest RECORDED clock time, never the wall
    clock, so replay reproduces the same batches.
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
            SessionInvocationBindingConflictedEvent.event_type,
            *ExecutionTerminalEventType,
        }
        if self._settlements is not None:
            types.add(InventoryReconciliationSweepEvent.event_type)
        return types

    async def handle(self, envelope: EventEnvelope[DomainEvent]) -> None:
        event_type = envelope.metadata.event_type
        if event_type in _TERMINAL_EVENT_TYPES:
            await self._project_terminal(envelope)
            return
        project = {
            SessionStartedEvent.event_type: self._project_session,
            SessionInvocationRecordedEvent.event_type: self._project_invocation,
            SessionInvocationBindingConflictedEvent.event_type: self._project_binding_conflict,
            InventoryReconciliationSweepEvent.event_type: self._record_clock,
        }.get(event_type or "")
        if project is not None:
            await project(envelope)

    async def _project_session(self, envelope: EventEnvelope[DomainEvent]) -> None:
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

    @staticmethod
    def _invocation_reference(envelope: EventEnvelope[DomainEvent]) -> EvidenceReference:
        return EvidenceReference(
            producer_id="syntropic-invocation-events",
            evidence_id=envelope.metadata.event_id,
            source_revision=str(envelope.metadata.aggregate_nonce),
            locator=f"AgentSession-{envelope.metadata.aggregate_id}",
            extractor_version="host-invocation-events/1",
        )

    async def _project_binding_conflict(self, envelope: EventEnvelope[DomainEvent]) -> None:
        event = SessionInvocationBindingConflictedEvent.model_validate_json(
            envelope.event.model_dump_json()
        )
        reference = self._invocation_reference(envelope)
        await self._evidence.append(
            EvidenceBatch(
                batch_id=envelope.metadata.event_id,
                producer_id=reference.producer_id,
                evidence=binding_conflict_evidence(event, self._source, reference),
            )
        )

    async def _project_invocation(self, envelope: EventEnvelope[DomainEvent]) -> None:
        event = SessionInvocationRecordedEvent.model_validate_json(envelope.event.model_dump_json())
        reference = self._invocation_reference(envelope)
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

    async def _record_clock(self, envelope: EventEnvelope[DomainEvent]) -> None:
        if self._settlements is None:
            return
        sweep = InventoryReconciliationSweepEvent.model_validate_json(
            envelope.event.model_dump_json()
        )
        await self._settlements.observe_clock(sweep.observed_at)

    async def release_deadlines(self) -> int:
        """Live-only work: call from ``process_pending()``, never during catch-up.

        Idempotent: the deadline batch is keyed by run, and a crash between the
        durable fact and ``settle()`` re-appends a byte-identical batch.
        """
        if self._settlements is None:
            return 0
        page = await self._settlements.due(limit=_DEADLINES_PER_SWEEP)
        for deadline in page.items:
            if deadline.run.source_instance_id != self._source:
                raise ValueError("settlement deadline belongs to another installation")
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
        return len(page.items)
