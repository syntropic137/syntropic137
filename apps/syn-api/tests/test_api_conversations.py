"""Tests for syn_api.routes.conversations — conversation log retrieval."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from syn_api.types import Err, ObservabilityError, Ok

# Ensure test environment for in-memory adapters
os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage and projections between tests."""
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture
def mock_conversation_store():
    """Mock conversation store with default None returns."""
    store = AsyncMock()
    store.retrieve_session = AsyncMock(return_value=None)
    store.get_session_metadata = AsyncMock(return_value=None)
    return store


def _patch_store(store: AsyncMock):
    """Patch get_conversation_store as an async function returning the mock store."""
    return patch(
        "syn_api.routes.conversations.get_conversation_store",
        new=AsyncMock(return_value=store),
    )


async def test_get_conversation_log(mock_conversation_store):
    """Retrieve a conversation log with 3 JSONL lines."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "content": "Hello"}',
        '{"type": "tool_use", "tool_name": "Read", "content": "reading file"}',
        '{"type": "assistant", "content": "Done"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("session-1")

    assert isinstance(result, Ok)
    log = result.value
    assert log.session_id == "session-1"
    assert log.total_lines == 3
    assert len(log.lines) == 3
    assert log.lines[0].line_number == 1
    assert log.lines[2].line_number == 3


async def test_get_conversation_log_not_found(mock_conversation_store):
    """Return Err NOT_FOUND when session has no log."""
    mock_conversation_store.retrieve_session.return_value = None

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("nonexistent")

    assert isinstance(result, Err)
    assert result.error == ObservabilityError.NOT_FOUND


async def test_get_conversation_log_pagination(mock_conversation_store):
    """Paginate with offset=2 limit=2 over 5 lines."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "content": "line1"}',
        '{"type": "assistant", "content": "line2"}',
        '{"type": "assistant", "content": "line3"}',
        '{"type": "assistant", "content": "line4"}',
        '{"type": "assistant", "content": "line5"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("session-1", offset=2, limit=2)

    assert isinstance(result, Ok)
    log = result.value
    assert log.total_lines == 5
    assert len(log.lines) == 2
    assert log.lines[0].line_number == 3
    assert log.lines[1].line_number == 4


async def test_get_conversation_log_parses_json(mock_conversation_store):
    """Verify event_type and tool_name are extracted from JSONL."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "tool_use", "tool_name": "Bash", "content": "ls -la"}',
        '{"type": "assistant", "content": "Here are the files"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("session-1")

    assert isinstance(result, Ok)
    lines = result.value.lines
    assert lines[0].event_type == "tool_use"
    assert lines[0].tool_name == "Bash"
    assert lines[0].content_preview == "ls -la"
    assert lines[1].event_type == "assistant"
    assert lines[1].tool_name is None


async def test_codex_agent_message_renders_as_talking(mock_conversation_store):
    """A codex ``agent_message`` item surfaces its text as readable conversation."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message",'
        '"text":"I will read the plan and implement it."}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "assistant"
    assert line.tool_name is None
    assert line.content_preview == "I will read the plan and implement it."


async def test_codex_command_execution_maps_to_bash_tool(mock_conversation_store):
    """A codex ``command_execution`` item maps to the Bash tool with its command."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.completed","item":{"id":"item_2","type":"command_execution",'
        '"command":"cat one.txt","aggregated_output":"alpha","exit_code":0,'
        '"status":"completed"}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "tool_use"
    assert line.tool_name == "Bash"
    # item.completed shows the result (aggregated_output), not the invocation -
    # see test_codex_command_execution_started_shows_invocation for the
    # started-side preview.
    assert line.content_preview == "alpha"


async def test_codex_command_execution_started_shows_invocation(mock_conversation_store):
    """An ``item.started`` command_execution shows the command being invoked."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.started","item":{"id":"item_2","type":"command_execution",'
        '"command":"cat one.txt","status":"in_progress"}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "tool_use"
    assert line.tool_name == "Bash"
    assert line.content_preview == "cat one.txt"


async def test_codex_command_execution_started_and_completed_differ(mock_conversation_store):
    """The started/completed pair for the SAME command carry different content.

    Regression guard: before the fix, both rows normalized to the command
    string and rendered as byte-identical duplicates.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.started","item":{"id":"item_2","type":"command_execution",'
        '"command":"cat one.txt","status":"in_progress"}}',
        '{"type":"item.completed","item":{"id":"item_2","type":"command_execution",'
        '"command":"cat one.txt","aggregated_output":"alpha","exit_code":0,'
        '"status":"completed"}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    started, completed = result.value.lines
    assert started.content_preview == "cat one.txt"
    assert completed.content_preview == "alpha"
    assert started.content_preview != completed.content_preview


async def test_codex_command_execution_completed_falls_back_to_command(mock_conversation_store):
    """An ``item.completed`` with empty aggregated_output falls back to the command."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.completed","item":{"id":"item_2","type":"command_execution",'
        '"command":"cat one.txt","aggregated_output":"","exit_code":0,'
        '"status":"completed"}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.content_preview == "cat one.txt"


async def test_codex_file_change_maps_to_edit_tool(mock_conversation_store):
    """A codex ``file_change`` item maps to the Edit tool with the changed paths."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.completed","item":{"id":"item_3","type":"file_change",'
        '"status":"completed","changes":[{"path":"src/a.py","kind":"modify"},'
        '{"path":"src/b.py","kind":"add"}]}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "tool_use"
    assert line.tool_name == "Edit"
    assert line.content_preview == "src/a.py, src/b.py"


async def test_codex_cli_stdin_banner_is_filtered(mock_conversation_store):
    """The codex ``Reading additional input from stdin`` banner is dropped entirely."""
    mock_conversation_store.retrieve_session.return_value = [
        "Reading additional input from stdin...",
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hello"}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    log = result.value
    assert log.total_lines == 1
    assert len(log.lines) == 1
    assert log.lines[0].content_preview == "hello"


async def test_codex_diagnostic_line_labelled_log_not_unknown(mock_conversation_store):
    """A non-JSON codex diagnostic line is labelled ``log``, never ``unknown``."""
    mock_conversation_store.retrieve_session.return_value = [
        "ERROR codex_models_manager::manager: transient upstream hiccup",
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "log"
    assert line.content_preview is not None


async def test_non_object_json_line_does_not_fail_whole_transcript(mock_conversation_store):
    """A bare JSON scalar/array line is labelled ``log``, not crash the request."""
    mock_conversation_store.retrieve_session.return_value = [
        "null",
        '["not", "an", "object"]',
        '{"type": "assistant", "content": "still here"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    lines = result.value.lines
    assert lines[0].event_type == "log"
    assert lines[1].event_type == "log"
    assert lines[2].event_type == "assistant"
    assert lines[2].content_preview == "still here"


async def test_claude_jsonl_lines_survive_noise_filter(mock_conversation_store):
    """Claude transcripts are pure JSONL, so the codex noise filter never drops them."""
    mock_conversation_store.retrieve_session.return_value = [
        # A claude assistant message whose text happens to mention a codex banner.
        '{"type": "assistant", "content": "Reading additional input from stdin is a codex banner"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    log = result.value
    assert log.total_lines == 1
    assert log.lines[0].event_type == "assistant"


async def test_get_conversation_metadata(mock_conversation_store):
    """Retrieve conversation metadata from store."""
    mock_conversation_store.get_session_metadata.return_value = {
        "event_count": 42,
        "model": "claude-sonnet-4-20250514",
        "total_input_tokens": 1000,
        "total_output_tokens": 500,
        "tool_counts": {"Bash": 5, "Read": 3},
        "started_at": "2026-03-23T10:00:00Z",
        "completed_at": "2026-03-23T10:05:00Z",
    }

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_metadata

        result = await get_conversation_metadata("session-1")

    assert isinstance(result, Ok)
    meta = result.value
    assert meta is not None
    assert meta.session_id == "session-1"
    assert meta.event_count == 42
    assert meta.model == "claude-sonnet-4-20250514"
    assert meta.total_input_tokens == 1000
    assert meta.total_output_tokens == 500
    assert meta.tool_counts == {"Bash": 5, "Read": 3}


async def test_get_conversation_metadata_not_found(mock_conversation_store):
    """Return Ok(None) when session metadata doesn't exist."""
    mock_conversation_store.get_session_metadata.return_value = None

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_metadata

        result = await get_conversation_metadata("nonexistent")

    assert isinstance(result, Ok)
    assert result.value is None
