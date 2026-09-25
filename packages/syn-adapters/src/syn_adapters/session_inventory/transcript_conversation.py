"""Translate the agentic-primitives conversation capability, never parse vendor rows."""

from __future__ import annotations

from typing import Literal

from agentic_isolation.harnesses import ConversationHarnessPlugin, get_harness

from syn_domain.contexts.agent_sessions import TranscriptConversation, TranscriptMessage


class AgenticTranscriptConversation:
    def conversation(
        self, harness: str, content: bytes, content_format: Literal["native", "envelope"]
    ) -> TranscriptConversation:
        plugin = get_harness(harness)
        if not isinstance(plugin, ConversationHarnessPlugin):
            return TranscriptConversation(
                supported=False, issues=("unsupported_harness_conversation",)
            )
        reader = plugin.conversation_reader()
        result = (
            reader.conversation_envelope(content)
            if content_format == "envelope"
            else reader.conversation(content)
        )
        return TranscriptConversation(
            supported=True,
            messages=tuple(
                TranscriptMessage(role=message.role, text=message.text, line=message.line)
                for message in result.messages
            ),
            truncated=result.truncated,
            issues=result.issues,
            reader_version=result.reader_version,
        )
