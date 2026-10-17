"""Near Duplicate matching over Screened Text (ADR-076-feedback-ticketing).

Pure. Word-shingle Jaccard similarity, compared only within a match bucket: the
same route, or the same type when there is no route. A near duplicate becomes a
Report on the matched ticket; the similarity is recorded on ``TicketReportAdded``.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import TicketType
from syn_domain.contexts.feedback.domain.ScreenedText import ScreenedText


class MatchBucket(BaseModel):
    """Two submissions are compared only when their buckets are equal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route: str | None
    type: TicketType | None

    @classmethod
    def of(cls, *, route: str | None, ticket_type: TicketType) -> MatchBucket:
        if route:
            return cls(route=route, type=None)
        return cls(route=None, type=ticket_type)


class MatchCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    bucket: MatchBucket
    text: ScreenedText


class NearDuplicateMatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    similarity: float = Field(ge=0.0, le=1.0)


class NearDuplicateMatcher:
    """Finds the most similar candidate at or above ``threshold``, or none."""

    def __init__(self, *, threshold: float = 0.6, shingle_size: int = 3) -> None:
        if not 0.0 < threshold <= 1.0:
            msg = f"threshold must be in (0, 1], got {threshold}"
            raise ValueError(msg)
        if shingle_size < 1:
            msg = f"shingle_size must be >= 1, got {shingle_size}"
            raise ValueError(msg)
        self._threshold = threshold
        self._size = shingle_size

    def best_match(
        self,
        text: ScreenedText,
        bucket: MatchBucket,
        candidates: Sequence[MatchCandidate],
    ) -> NearDuplicateMatch | None:
        mine = self._shingles(text)
        best: NearDuplicateMatch | None = None
        for candidate in candidates:
            if candidate.bucket != bucket:
                continue
            similarity = _jaccard(mine, self._shingles(candidate.text))
            if similarity >= self._threshold and (best is None or similarity > best.similarity):
                best = NearDuplicateMatch(ticket_id=candidate.ticket_id, similarity=similarity)
        return best

    def _shingles(self, text: ScreenedText) -> frozenset[tuple[str, ...]]:
        words = text.text.casefold().split()
        if len(words) <= self._size:
            return frozenset({tuple(words)}) if words else frozenset()
        return frozenset(
            tuple(words[i : i + self._size]) for i in range(len(words) - self._size + 1)
        )


def _jaccard(a: frozenset[tuple[str, ...]], b: frozenset[tuple[str, ...]]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
