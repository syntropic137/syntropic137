"""``StoredConversationLogReader``: one stored log line in, one row out (#1424).

The API route's own behaviour pin is ``apps/syn-api/tests/test_api_conversations.py``,
which reaches this reader through ``_wiring``. These tests pin the adapter
directly, one harness shape at a time, so a regression names the shape it broke.
"""

from __future__ import annotations

import json

import pytest

from syn_adapters.conversations import StoredConversationLogReader
from syn_domain.contexts.agent_sessions import ConversationLogReader, ConversationLogRow

_SEP = " ¦ "


def _row(record: object) -> ConversationLogRow:
    return StoredConversationLogReader().read_row(json.dumps(record))


@pytest.mark.unit
def test_satisfies_the_port() -> None:
    reader: ConversationLogReader = StoredConversationLogReader()
    assert reader.belongs_in_log("{}")


@pytest.mark.unit
def test_claude_tool_use_names_every_block_and_its_salient_input() -> None:
    row = _row(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "looking"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}},
                ]
            },
        }
    )
    assert row == ConversationLogRow(
        event_type="tool_use",
        tool_name=f"Bash{_SEP}Read",
        content_preview=f"ls -la{_SEP}/a.py",
    )


@pytest.mark.unit
def test_claude_tool_result_list_content_and_is_error() -> None:
    row = _row(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "content": [{"type": "text", "text": "\nfirst line\nsecond"}],
                    },
                    {"type": "tool_result", "content": "boom\nmore", "is_error": True},
                ]
            },
        }
    )
    # A line of only tool_results keeps its own type and names no tool.
    assert row == ConversationLogRow(
        event_type="user",
        tool_name=None,
        content_preview=f"first line{_SEP}[error] boom",
    )


@pytest.mark.unit
def test_codex_file_change_lists_its_paths() -> None:
    row = _row(
        {
            "type": "item.completed",
            "item": {"type": "file_change", "changes": [{"path": "a.py"}, {"path": "b/c.py"}]},
        }
    )
    assert row == ConversationLogRow(
        event_type="tool_use", tool_name="Edit", content_preview="a.py, b/c.py"
    )


@pytest.mark.unit
def test_codex_command_execution_prefers_output_then_command() -> None:
    completed = {"type": "command_execution", "command": "pytest -q", "aggregated_output": ""}
    row = _row({"type": "item.completed", "item": completed})
    assert row == ConversationLogRow(
        event_type="tool_use", tool_name="Bash", content_preview="pytest -q"
    )
    with_output = {**completed, "aggregated_output": "3 passed"}
    assert _row({"type": "item.completed", "item": with_output}).content_preview == "3 passed"
    # item.started never duplicates the completed tool row.
    assert _row({"type": "item.started", "item": completed}) == ConversationLogRow(
        event_type="system", tool_name=None, content_preview=None
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "line",
    [
        "Reading additional input from stdin...",
        "  warning: --full-auto is deprecated; use --sandbox",
    ],
)
def test_codex_cli_noise_does_not_belong_in_the_log(line: str) -> None:
    assert StoredConversationLogReader().belongs_in_log(line) is False


@pytest.mark.unit
@pytest.mark.parametrize("line", ["ERROR codex_core: request failed", '{"type": "Reading"}', ""])
def test_other_lines_belong_in_the_log(line: str) -> None:
    assert StoredConversationLogReader().belongs_in_log(line) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "preview"),
    [
        ("ERROR codex_core: request failed {", "ERROR codex_core: request failed {"),
        ("null", "null"),
        ("[1, 2]", "[1, 2]"),
        ("   ", None),
    ],
)
def test_malformed_line_is_a_log_row_not_an_error(raw: str, preview: str | None) -> None:
    assert StoredConversationLogReader().read_row(raw) == ConversationLogRow(
        event_type="log", tool_name=None, content_preview=preview
    )
