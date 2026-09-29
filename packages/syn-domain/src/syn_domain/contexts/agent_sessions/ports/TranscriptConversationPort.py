"""Harness-neutral conversation preview boundary. Format knowledge lives upstream."""

from typing import Literal, Protocol

from syn_domain.contexts.agent_sessions.domain.read_models.transcript_conversation import (
    TranscriptConversation,
    TranscriptMessage,
)

__all__ = ["TranscriptConversation", "TranscriptConversationPort", "TranscriptMessage"]


class TranscriptConversationPort(Protocol):
    def conversation(
        self,
        harness: str,
        content: bytes,
        content_format: Literal["native", "envelope"],
        native_id: str | None = None,
    ) -> TranscriptConversation:
        """Return a bounded user/assistant excerpt; never raise on malformed input.

        ``native_id`` is the captured transcript's own identity; a document that
        embeds another transcript's rows is previewed as this identity only.
        """
        ...
