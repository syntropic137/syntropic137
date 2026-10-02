"""Transcript issues belong to the revision they were extracted from (#1398).

A live transcript is captured repeatedly while it grows. An extractor issue
describes one archived revision: a revision taken between an Agent call and its
result reports ``unresolved_spawn`` although the next revision resolves it.
A later local revision whose bytes are present describes the transcript's
current content, so it supersedes the issues extracted from earlier receipts.
A later receipt without content (pending, missing, expired) supersedes nothing.
Receipt sequences are comparable only within one producer's stream, as in
``coverage_settlement.latest_capture_states``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        SessionEvidence,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        EvidenceReference,
    )


def without_superseded_revision_issues(evidence: SessionEvidence) -> SessionEvidence:
    """Drop extractor issues of a receipt that a later present revision superseded."""
    local = [item for item in evidence.captures if item.destination == "local"]
    latest_present: dict[tuple[str, str], int] = {}
    for item in local:
        if item.availability is BodyAvailability.PRESENT:
            stream = (item.evidence.producer_id, item.node.key)
            latest_present[stream] = max(latest_present.get(stream, -1), item.receipt_sequence)
    # The capture handler records a revision's issues under that revision's own
    # reference (its archive hash is the source revision), so the full reference
    # links an issue to exactly one revision; nothing else shares it.
    superseded: list[EvidenceReference] = [
        item.evidence
        for item in local
        if item.receipt_sequence
        < latest_present.get((item.evidence.producer_id, item.node.key), -1)
    ]
    if not superseded:
        return evidence
    return evidence.model_copy(
        update={
            "acquisition_gaps": tuple(
                item for item in evidence.acquisition_gaps if item.evidence not in superseded
            )
        }
    )
