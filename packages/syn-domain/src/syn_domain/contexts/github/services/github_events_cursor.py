"""GitHubEventsCursor - typed cursor for GitHub Events API polling.

Encodes ETag (HTTP conditional caching) + ``last_event_id`` (high-water mark
for content-based filtering). Both fields are REQUIRED at construction,
making the fix for #694 non-bypassable: any caller persisting a cursor must
supply the HWM.

See ADR-060 Section 9 for the eight-layer defense in depth.
"""

from __future__ import annotations

from dataclasses import dataclass

from event_sourcing.core.historical_poller import CursorData


@dataclass(frozen=True, slots=True)
class GitHubEventsCursor:
    """Typed cursor for the GitHub Events API.

    Both fields are required. Empty strings are valid (they mean "no prior
    state") but ``None`` is forbidden by the type system, preventing the
    silent metadata-omission bug pattern.

    Attributes:
        etag: HTTP ETag from the previous response (Layer 1: HTTP 304).
        last_event_id: Highest GitHub Events API event ID seen
            (Layer 2: HWM filtering inside ``fetch()``). Numeric string per
            GitHub's spec; integer comparison is used (lexicographic would
            misorder unequal-length IDs). Empty string means "no events ever
            processed."
    """

    etag: str
    last_event_id: str

    def to_cursor_data(self) -> CursorData:
        """Encode for ESP's generic ``CursorStore``."""
        return CursorData(
            value=self.etag,
            metadata={"last_event_id": self.last_event_id},
        )

    @classmethod
    def from_cursor_data(cls, data: CursorData | None) -> GitHubEventsCursor:
        """Decode from ESP's generic ``CursorStore``.

        Returns an empty cursor (treat as cold start) if ``data`` is None or
        ``metadata`` is missing.
        """
        if data is None:
            return cls(etag="", last_event_id="")
        last_event_id = ""
        if data.metadata:
            last_event_id = data.metadata.get("last_event_id", "")
        return cls(etag=data.value, last_event_id=last_event_id)

    def is_newer_than(self, event_id: str) -> bool:
        """Return ``True`` if the given event ID is greater than the HWM.

        GitHub event IDs are numeric strings, monotonically increasing per
        source. Lexicographic comparison would break on length differences,
        so compare as integers. An empty ``last_event_id`` (cold cursor)
        accepts everything.
        """
        if not self.last_event_id:
            return True
        try:
            return int(event_id) > int(self.last_event_id)
        except (TypeError, ValueError):
            return False
