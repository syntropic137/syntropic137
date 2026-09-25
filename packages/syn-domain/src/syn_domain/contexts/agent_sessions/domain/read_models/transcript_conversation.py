"""A bounded, role-normalized excerpt of a transcript, independent of source format.

A preview is a read convenience for people, never evidence: exact archived
bytes remain the source of truth and the only download.
"""

from typing import Literal

from pydantic import Field

from .session_inventory import Identifier, InventoryModel


class TranscriptMessage(InventoryModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=32_768)
    line: int = Field(ge=1)


class TranscriptConversation(InventoryModel):
    """``supported`` is False when no reader exists for this harness or format."""

    supported: bool
    messages: tuple[TranscriptMessage, ...] = ()
    truncated: bool = False
    issues: tuple[Identifier, ...] = ()
    reader_version: Identifier | None = None
