"""Normalize host invocation facts without interpreting harness wire formats."""

from syn_domain.contexts.agent_sessions.domain.events.SessionInvocationRecordedEvent import (
    SessionInvocationRecordedEvent,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    CoverageContract,
    IdentityBindingEvidence,
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


def invocation_evidence(
    event: SessionInvocationRecordedEvent, source: str, reference: EvidenceReference
) -> SessionEvidence:
    run = RunIdentity(source_instance_id=source, execution_id=event.execution_id)
    invocation = InventoryNodeRef(
        kind="invocation",
        source_instance_id=source,
        local_id=event.invocation_id,
    )
    platform = InventoryNodeRef(
        kind="platform", source_instance_id=source, local_id=event.session_id
    )
    bindings: tuple[IdentityBindingEvidence, ...] = ()
    if event.native_session_id is not None:
        bindings = (
            IdentityBindingEvidence(
                owner=invocation,
                transcript=InventoryNodeRef(
                    kind="transcript",
                    source_instance_id=source,
                    local_id=event.native_session_id,
                    harness=event.harness,
                ),
                confidence=EvidenceClass.REGISTERED,
                evidence=reference,
            ),
        )
    return SessionEvidence(
        run=run,
        nodes=(NodeEvidence(node=invocation, evidence=reference),),
        memberships=tuple(
            MembershipEvidence(
                node=node,
                run=run,
                phase_id=event.phase_id,
                attempt_id=event.attempt_id,
                confidence=EvidenceClass.REGISTERED,
                evidence=reference,
            )
            for node in (invocation, platform)
        ),
        bindings=bindings,
        # Independent expectation exists before any native ID or bytes arrive.
        # Process exit alone never seals descendant/capture coverage: the host
        # seal is derived from execution settlement facts by the resolver
        # (coverage_settlement.py), never asserted by one invocation's event.
        coverage_contract=CoverageContract(
            contract_id="syntropic-invocations/1",
            expected_nodes=(invocation,),
            sealed=False,
        )
        if event.status == "registered"
        else None,
    )
