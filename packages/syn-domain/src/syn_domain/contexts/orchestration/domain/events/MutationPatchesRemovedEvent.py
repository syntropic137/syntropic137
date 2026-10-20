"""MutationPatchesRemoved event - the platform's S -> S' commit (plan §A.4)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event


@event("MutationPatchesRemoved", "v1")
class MutationPatchesRemovedEvent(DomainEvent):
    """A write the platform made, and the provenance that keeps evidence about S valid at S'."""

    execution_id: str
    gate_id: str
    step: int
    repository: str
    branch: str
    before_sha: str
    after_sha: str
    author: str
