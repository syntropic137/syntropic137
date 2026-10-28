"""A command's combined output, reduced to a scrubbed tail as it arrives (ADR-078 D3).

``stream()`` yields whole lines, so ``LineDecoder`` holds an unterminated line
whole: a build printing a progress bar without newlines grows executor memory
until it ends. A command phase keeps only the last few KiB, so this consumes
raw pages and never holds more than one page plus ``max_line_chars``.

Credentials are withheld BEFORE anything is retained, with the same scrubber
``stream()`` uses. Whole lines are scrubbed as lines, exactly as there. A line
too long to hold is cut, and the last ``scrubber.reach`` characters are held
back at the cut, so a value split across two pages is whole when scrubbed.
"""

from __future__ import annotations

import codecs
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.agentic.credential_scrubber import CredentialScrubber

#: The longest unterminated line held before it is cut. Far above any line a
#: person reads, far below anything that matters to executor memory.
MAX_LINE_CHARS = 64 * 1024

_UTF8_CONTINUATION_MASK = 0xC0
_UTF8_CONTINUATION = 0x80


class BoundedOutput:
    """Feed pages in; read ``tail`` and ``dropped_bytes`` out."""

    def __init__(
        self,
        tail_bytes: int,
        *,
        launch_line: str | None = None,
        max_line_chars: int = MAX_LINE_CHARS,
    ) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._partial = ""
        self._ring = bytearray()
        self._tail_bytes = tail_bytes
        self._max_line_chars = max_line_chars
        # The platform's own launch announcement (#1879) is not the command's
        # output, so it is not what a person reading the tail should see.
        self._launch_line = launch_line
        self.dropped_bytes = 0

    def feed(self, data: bytes, scrubber: CredentialScrubber) -> None:
        text = self._partial + self._decoder.decode(data)
        *complete, self._partial = text.split("\n")
        for line in complete:
            if self._launch_line is not None and line.rstrip("\r") == self._launch_line:
                self._launch_line = None
                continue
            self._retain(scrubber.scrub(line) + "\n")
        if len(self._partial) > self._max_line_chars:
            scrubbed = scrubber.scrub(self._partial)
            cut = len(scrubbed) - scrubber.reach
            self._retain(scrubbed[:cut])
            self._partial = scrubbed[cut:]

    def gap(self, lost_bytes: int | None) -> None:
        """The provider evicted output before it was read: the severed line goes too."""
        self.dropped_bytes += len(self._partial.encode()) + (lost_bytes or 0)
        self._partial = ""
        self._decoder.reset()

    def finish(self, scrubber: CredentialScrubber) -> None:
        text = self._partial + self._decoder.decode(b"", final=True)
        self._partial = ""
        if text:
            self._retain(scrubber.scrub(text))

    @property
    def tail(self) -> str:
        """The retained bytes as text, from the first whole character."""
        start = 0
        while (
            start < len(self._ring)
            and self._ring[start] & _UTF8_CONTINUATION_MASK == _UTF8_CONTINUATION
        ):
            start += 1
        return self._ring[start:].decode("utf-8", errors="replace")

    def _retain(self, text: str) -> None:
        self._ring += text.encode()
        excess = len(self._ring) - self._tail_bytes
        if excess > 0:
            self.dropped_bytes += excess
            del self._ring[:excess]
