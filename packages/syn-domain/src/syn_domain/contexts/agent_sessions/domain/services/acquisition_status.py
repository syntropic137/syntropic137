"""Resolve host-sequenced read outcomes independently for each acquisition stream."""

from collections import defaultdict

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    AcquisitionGapEvidence,
    AcquisitionStatusEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import InventoryGap


def acquisition_gaps(
    statuses: tuple[AcquisitionStatusEvidence, ...],
) -> tuple[AcquisitionGapEvidence, ...]:
    grouped: dict[tuple[str, str], list[AcquisitionStatusEvidence]] = defaultdict(list)
    for status in statuses:
        grouped[(status.evidence.producer_id, status.stream_id)].append(status)
    gaps = []
    for key in sorted(grouped):
        observations = grouped[key]
        latest = max(item.sequence for item in observations)
        # Conflicting same-sequence outcomes cannot hide a reported failure.
        for item in observations:
            if item.sequence == latest and item.failed:
                gaps.append(
                    AcquisitionGapEvidence(
                        gap=InventoryGap(
                            reason=item.reason, evidence_ids=(item.evidence.evidence_id,)
                        ),
                        evidence=item.evidence,
                    )
                )
    return tuple(gaps)
