"""Resolving a delegated session's usage from the session store (#895).

This is the seam between "a delegate ran" and "here is what it cost". It
fetches one stored session and turns it into usage, and it exists as its own
module because the RETRIEVAL is where the mistakes were: two consecutive
review rounds found defects that unit tests missed entirely, because every
test passed the values the code expected rather than the values the store
emits.

Everything here fails toward UNPRICED rather than toward zero. A delegate
whose transcript is missing, unreachable or unreadable may have cost real
money, and reporting it as free is the failure this issue exists to remove.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from syn_domain.contexts.agent_sessions.transcript_usage import (
    StoredTranscript,
    UnpricedUsage,
    UsageResult,
    extract_usage,
)


@dataclass(frozen=True)
class StoredSession:
    """One session as a conforming store hands it over.

    ``source_format`` and ``raw`` are taken from the record rather than
    inferred. Inferring the format is what produced a literal matching no real
    record, and assuming the raw shape is what silently unpriced an entire
    harness.
    """

    session_id: str
    source_format: str
    raw: StoredTranscript
    model: str | None = None
    """The store reports a model in metadata. Advisory: the transcript is the
    authority, because a delegate can switch model mid-session and only the
    transcript records that."""


@runtime_checkable
class SessionStorePort(Protocol):
    """Reads one session back out of the store."""

    async def fetch_session(self, session_id: str) -> StoredSession | None:
        """The stored session, or None if the store does not have it."""
        ...


async def resolve_delegate_usage(store: SessionStorePort, session_id: str) -> UsageResult:
    """Fetch a delegated session and recover what it used.

    Degrades rather than raises, in every branch. An import runs over many
    sessions, and one that is missing, unreachable or unreadable must cost
    that session its price rather than costing the whole import its run.
    """
    try:
        session = await store.fetch_session(session_id)
    except Exception as exc:
        # Deliberately broad. Anything the transport can raise, from a reset
        # connection to a malformed response, means the same thing here: this
        # session's cost is unknown, and the sessions beside it are not.
        return UnpricedUsage(f"store lookup failed for {session_id!r}: {exc}")

    if session is None:
        # Absent is not free. A delegate may have run and cost money while its
        # transcript never reached the store, and saying "unknown" is the only
        # honest answer available.
        return UnpricedUsage(f"no stored session for {session_id!r}")

    return extract_usage(session.source_format, session.raw)
