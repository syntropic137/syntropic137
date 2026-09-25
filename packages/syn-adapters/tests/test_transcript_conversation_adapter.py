"""The adapter translates the AP conversation capability; it knows no row format."""

from __future__ import annotations

import json

import pytest

from syn_adapters.session_inventory.transcript_conversation import (
    AgenticTranscriptConversation,
)

pytestmark = pytest.mark.unit


def _jsonl(*rows: object) -> bytes:
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode()


# Fixture rows are harness data handed to agentic-primitives, not parsed here.
_CODEX = _jsonl(
    {"type": "session_meta", "payload": {"id": "s", "instructions": "x" * 50_000}},
    {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"text": "<environment_context>"}],
        },
    },
    {
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "item": {
                "type": "UserMessage",
                "id": "u",
                "content": [{"type": "text", "text": "Spawn a child"}],
            },
        },
    },
)


def test_native_and_envelope_inputs_become_role_normalized_messages() -> None:
    adapter = AgenticTranscriptConversation()
    native = adapter.conversation("codex", _CODEX, "native")
    assert native.supported
    assert [(m.role, m.text, m.line) for m in native.messages] == [("user", "Spawn a child", 3)]
    envelope = json.dumps(
        {
            "agent": "Codex",
            "source_format": "codex-rollout-jsonl",
            "session_id": "s",
            "raw": _CODEX.decode(),
        }
    ).encode()
    assert adapter.conversation("codex", envelope, "envelope").messages == native.messages


def test_unknown_harness_is_explicitly_unsupported() -> None:
    result = AgenticTranscriptConversation().conversation("unknown", b"anything", "native")
    assert not result.supported
    assert result.messages == ()
    assert result.issues == ("unsupported_harness_conversation",)


def test_captured_identity_selects_whose_turns_are_shown() -> None:
    side = {"type": "user", "sessionId": "s", "isSidechain": True, "agentId": "b"}
    content = _jsonl(
        {**side, "message": {"role": "user", "content": "child task"}},
        {"type": "user", "sessionId": "s", "message": {"role": "user", "content": "root turn"}},
    )
    adapter = AgenticTranscriptConversation()
    root = adapter.conversation("claude", content, "native", "s")
    child = adapter.conversation("claude", content, "native", "agent-b")
    assert [m.text for m in root.messages] == ["root turn"]
    assert [m.text for m in child.messages] == ["child task"]
