"""Acquisition recovery uses durable host sequence, never delivery order."""

from itertools import permutations

import pytest
from pydantic import ValidationError

from syn_domain.contexts.agent_sessions import EvidenceBatch, RunIdentity, SessionEvidence
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    AcquisitionStatusEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceReference,
    EvidenceRetraction,
)
from syn_domain.contexts.agent_sessions.domain.services.evidence_assembly import assemble_evidence
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    resolve_relationships,
)
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import StoredEvidenceBatch

pytestmark = pytest.mark.unit
RUN = RunIdentity(source_instance_id="source", execution_id="run")


def status(sequence: int, *, failed: bool, producer: str = "host-a") -> AcquisitionStatusEvidence:
    return AcquisitionStatusEvidence(
        stream_id="children",
        sequence=sequence,
        failed=failed,
        reason="child_journal_unreadable",
        evidence=EvidenceReference(
            producer_id=producer,
            evidence_id=f"{sequence}:{failed}",
            source_revision=str(sequence),
            locator="children.sqlite",
            extractor_version="test/1",
        ),
    )


def test_latest_host_sequence_wins_under_reordering_duplicates_and_restart() -> None:
    observations = (status(3, failed=True), status(4, failed=False), status(2, failed=True))
    revisions = set()
    for order in permutations(observations):
        stored = tuple(
            StoredEvidenceBatch(
                sequence=i,
                batch=EvidenceBatch(
                    batch_id=str(i),
                    producer_id="host-a",
                    evidence=SessionEvidence(run=RUN, acquisition_statuses=(item,)),
                ),
            )
            for i, item in enumerate((*order, order[0]), start=1)
        )
        restored = tuple(
            StoredEvidenceBatch.model_validate_json(item.model_dump_json()) for item in stored
        )
        resolved = resolve_relationships(assemble_evidence(RUN, restored))
        assert not resolved.gaps
        revisions.add(resolved.revision)
    assert len(revisions) == 1


def test_other_producer_cannot_clear_failure_and_same_sequence_conflict_is_conservative() -> None:
    failed = status(3, failed=True)
    for success in (status(99, failed=False, producer="host-b"), status(3, failed=False)):
        result = resolve_relationships(
            SessionEvidence(run=RUN, acquisition_statuses=(failed, success))
        )
        assert any(gap.reason == "child_journal_unreadable" for gap in result.gaps)


def test_retracted_success_restores_unresolved_failure() -> None:
    failed, success = status(3, failed=True), status(4, failed=False)
    result = resolve_relationships(
        SessionEvidence(
            run=RUN,
            acquisition_statuses=(failed, success),
            retractions=(
                EvidenceRetraction(
                    target=success.evidence, evidence=status(5, failed=True).evidence
                ),
            ),
        )
    )
    assert any(gap.reason == "child_journal_unreadable" for gap in result.gaps)


def test_statuses_count_toward_evidence_batch_limit() -> None:
    with pytest.raises(ValidationError, match="500"):
        EvidenceBatch(
            batch_id="oversized",
            producer_id="host-a",
            evidence=SessionEvidence(run=RUN, acquisition_statuses=(status(1, failed=True),) * 501),
        )
