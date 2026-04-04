"""Server-side partial-ID prefix resolution for API routes.

Enables CLI users to pass short ID prefixes (e.g. first 8 chars) instead of
full UUIDs. Routes call resolve_or_raise() which:
1. Tries exact match first (fast path, no behavior change)
2. On miss, scans for prefix matches via the projection store
3. Returns full ID if unique, 404 if none, 409 if ambiguous

See: GitHub issue #508
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from syn_adapters.projection_stores.prefix_match import (
    format_ambiguous_error,
    resolve_by_prefix,
)

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol


async def resolve_or_raise(
    store: ProjectionStoreProtocol,
    namespace: str,
    partial_id: str,
    entity_type: str,
) -> str:
    """Resolve a (possibly partial) ID to a full ID, or raise HTTPException.

    Args:
        store: The projection store to query.
        namespace: The projection namespace (e.g. "workflow_details").
        partial_id: The ID provided by the client (full or partial).
        entity_type: Human-readable entity name for error messages.

    Returns:
        The resolved full ID.

    Raises:
        HTTPException: 404 if no match, 409 Conflict if ambiguous.
    """
    result = await resolve_by_prefix(store, namespace, partial_id)

    if result.is_exact:
        assert result.full_id is not None  # narrowing for type checker
        return result.full_id

    if result.is_ambiguous:
        raise HTTPException(
            status_code=409,
            detail=format_ambiguous_error(entity_type, partial_id, result.candidates),
        )

    raise HTTPException(
        status_code=404,
        detail=f"{entity_type} not found: {partial_id}",
    )
