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
    {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": "no"}},
    {
        "type": "response_item",
        "payload": {"type": "message", "role": "user", "content": [{"text": "Spawn a child"}]},
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
