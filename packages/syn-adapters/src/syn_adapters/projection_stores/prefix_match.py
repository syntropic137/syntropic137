"""Partial-ID prefix matching for projection stores.

Provides server-side resolution of short ID prefixes to full entity IDs,
enabling CLI users to type partial IDs instead of full UUIDs.

See: GitHub issue #508
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol


@dataclass(frozen=True)
class PrefixMatchResult:
    """Result of a prefix match attempt.

    Attributes:
        full_id: The resolved full ID, or None if no unique match.
        candidates: All matching IDs (for ambiguous error messages).
    """

    full_id: str | None
    candidates: list[str]

    @property
    def is_exact(self) -> bool:
        """True if exactly one match was found."""
        return self.full_id is not None

    @property
    def is_ambiguous(self) -> bool:
        """True if multiple matches were found."""
        return len(self.candidates) > 1

    @property
    def is_not_found(self) -> bool:
        """True if no matches were found."""
        return len(self.candidates) == 0


async def resolve_by_prefix(
    store: ProjectionStoreProtocol,
    namespace: str,
    partial_id: str,
) -> PrefixMatchResult:
    """Resolve a partial ID prefix to a full ID via the projection store.

    Tries exact match first (fast path), then falls back to prefix scan.
    Returns a PrefixMatchResult with the resolved ID or candidate list.

    Args:
        store: The projection store to query.
        namespace: The projection namespace (e.g. "workflow_details").
        partial_id: The partial ID to resolve (could be full or prefix).

    Returns:
        PrefixMatchResult with the match outcome.
    """
    # Fast path: try exact match first
    exact = await store.get(namespace, partial_id)
    if exact is not None:
        return PrefixMatchResult(full_id=partial_id, candidates=[partial_id])

    # Prefix scan — store returns up to 10 matches
    matches = await store.get_by_prefix(namespace, partial_id)

    if len(matches) == 1:
        full_id = matches[0][0]
        return PrefixMatchResult(full_id=full_id, candidates=[full_id])

    candidate_ids = [m[0] for m in matches]
    return PrefixMatchResult(full_id=None, candidates=candidate_ids)


def format_ambiguous_error(entity_type: str, partial_id: str, candidates: list[str]) -> str:
    """Format a human-readable error for ambiguous prefix matches.

    Args:
        entity_type: The entity type name (e.g. "Workflow", "Execution").
        partial_id: The partial ID that was ambiguous.
        candidates: List of matching full IDs.

    Returns:
        A formatted error message string.
    """
    preview = candidates[:5]
    lines = [
        f"Ambiguous {entity_type.lower()} ID '{partial_id}' matches {len(candidates)} entries:"
    ]
    for cid in preview:
        lines.append(f"  - {cid[:12]}...")
    if len(candidates) > 5:
        lines.append(f"  ... and {len(candidates) - 5} more")
    lines.append("Provide a longer prefix to disambiguate.")
    return "\n".join(lines)
