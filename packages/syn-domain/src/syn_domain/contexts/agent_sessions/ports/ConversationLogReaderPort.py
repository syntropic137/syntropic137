"""Port for reading one line of a stored conversation log (issue #1424).

WHY THIS IS A PORT. A conversation log is the agent's raw stdout, stored line
by line, and how a line spells a tool call, a tool result or a CLI banner
changes when Anthropic or OpenAI ships a new CLI. What a line MEANS to a reader
of the log does not: an event type, the tools it names and a short preview.
The API owns paging and the response shape and depends on this Protocol for
the rest, so no format literal leaks into the route.

Not ``TranscriptConversationPort``: that one reads a whole inventory document
into a bounded user/assistant excerpt. This one reads a single stored log line
into a single row, and every line keeps its row.

The implementation is ``syn_adapters.conversations.StoredConversationLogReader``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConversationLogRow:
    """What one stored conversation-log line shows, independent of harness.

    ``tool_name`` and ``content_preview`` carry one segment per entry on the
    line, joined by a separator the reader owns; segment *i* of both describes
    the same entry. Either is None when no entry on the line contributed to it.
    """

    event_type: str | None
    tool_name: str | None
    content_preview: str | None


class ConversationLogReader(Protocol):
    """Reads stored conversation-log lines into harness-neutral rows."""

    def belongs_in_log(self, raw: str) -> bool:
        """False for pure CLI chrome a harness writes beside its events.

        Such a line is dropped before numbering, so line numbers and totals
        count only real conversation content. MUST NOT raise.
        """
        ...

    def read_row(self, raw: str) -> ConversationLogRow:
        """The row ``raw`` renders as.

        Implementations MUST NOT raise. A non-JSON line, a JSON scalar or a
        line of an unknown shape is still a row (a ``log`` line or the generic
        reading): one odd line never fails the whole conversation log.
        """
        ...
