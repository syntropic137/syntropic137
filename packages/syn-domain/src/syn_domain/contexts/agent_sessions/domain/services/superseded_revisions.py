"""Transcript issues belong to the revision they were extracted from (#1398).

A live transcript is captured repeatedly while it grows. An extractor issue
describes one archived revision: a revision taken between an Agent call and its
result reports ``unresolved_spawn`` although the next revision resolves it.
Only the latest receipt of a transcript describes its current content, so an
issue from an earlier receipt of the same transcript is superseded. Receipt
sequences are comparable only within one producer's stream, as in
``coverage_settlement.latest_capture_states``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        SessionEvidence,
    )


def without_superseded_revision_issues(evidence: SessionEvidence) -> SessionEvidence:
    """Drop acquisition gaps raised by a receipt that a later receipt superseded."""
    latest: dict[tuple[str, str], int] = {}
    for item in evidence.captures:
        stream = (item.evidence.producer_id, item.node.key)
        latest[stream] = max(latest.get(stream, -1), item.receipt_sequence)
    superseded = {
        (item.evidence.producer_id, item.evidence.evidence_id)
        for item in evidence.captures
        if item.receipt_sequence < latest[(item.evidence.producer_id, item.node.key)]
    }
    if not superseded:
        return evidence
    return evidence.model_copy(
        update={
            "acquisition_gaps": tuple(
                item
                for item in evidence.acquisition_gaps
                if (item.evidence.producer_id, item.evidence.evidence_id) not in superseded
            )
        }
    )
