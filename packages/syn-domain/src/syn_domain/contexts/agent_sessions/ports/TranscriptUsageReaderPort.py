"""Port for recovering token usage from a stored transcript (issue #1424).

WHY THIS IS A PORT. How a stored transcript spells its usage - which record
type carries it, whether input includes cache reads, whether counts are
deltas or running totals - changes when Anthropic or OpenAI ships a new CLI.
What the answer MEANS does not: ``PricedUsage`` in disjoint buckets,
``NoUsage``, or ``UnpricedUsage`` with a retry disposition. The domain owns
the second and depends on this Protocol for the first, so pricing and
attribution are testable against a double and no format literal leaks in.

The implementation is ``syn_adapters.session_store.StoredTranscriptUsageReader``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.transcript_usage import (
        StoredTranscript,
        UsageResult,
    )


class TranscriptUsageReader(Protocol):
    """Reads what one stored transcript says it used."""

    def read_usage(self, source_format: str, document: StoredTranscript) -> UsageResult:
        """The usage ``document`` records, read as ``source_format``.

        ``source_format`` is the store's own label for the record, passed
        through as received rather than inferred.

        Implementations MUST NOT raise. A malformed transcript, an unknown
        format or a document of the wrong shape is ``UnpricedUsage``: one
        unreadable session costs that session its price, never the import of
        every session beside it.
        """
        ...
