"""Where a session's conversation lives in object storage (#1241).

One function, one mapping. A conversation is written to MinIO under a key,
and that same key is recorded in the Postgres index and rebuilt later by the
reader. Three derivations of the same string is three chances to derive it
differently, and the one that got it wrong did not fail - it filed the object
under a name the index could never point at, and the read reported that no
conversation had ever been recorded.

So the mapping lives here, alone, and it canonicalises on the way through: the
key is always built from the storable form of the id, whatever form the caller
happened to be holding.
"""

from __future__ import annotations

from syn_adapters.postgres_text import pg_safe

__all__ = ["conversation_object_key"]


def conversation_object_key(session_id: str) -> str:
    """The object key holding ``session_id``'s conversation log.

    Canonicalises the id first (see :func:`~syn_adapters.postgres_text.pg_safe`),
    so a key and the index row naming it are derived from the same characters
    even when the caller was holding the raw form. ``pg_safe`` is idempotent, so
    passing an already-canonical id gives the same answer.
    """
    return f"sessions/{pg_safe(session_id)}/conversation.jsonl"
