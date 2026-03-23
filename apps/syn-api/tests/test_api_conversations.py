"""Tests for syn_api.routes.conversations — conversation log retrieval."""

import os

import pytest
from unittest.mock import AsyncMock, patch

from syn_api.types import Err, Ok, ObservabilityError

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


async def test_get_conversation_log(mock_conversation_store):
    """Retrieve a conversation log with 3 JSONL lines."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "content": "Hello"}',
        '{"type": "tool_use", "tool_name": "Read", "content": "reading file"}',
        '{"type": "assistant", "content": "Done"}',
    ]

    with patch(
        "syn_api.routes.conversations.get_conversation_store", return_value=mock_conversation_store
    ):
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

    with patch(
        "syn_api.routes.conversations.get_conversation_store", return_value=mock_conversation_store
    ):
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

    with patch(
        "syn_api.routes.conversations.get_conversation_store", return_value=mock_conversation_store
    ):
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

    with patch(
        "syn_api.routes.conversations.get_conversation_store", return_value=mock_conversation_store
    ):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("session-1")

    assert isinstance(result, Ok)
    lines = result.value.lines
    assert lines[0].event_type == "tool_use"
    assert lines[0].tool_name == "Bash"
    assert lines[0].content_preview == "ls -la"
    assert lines[1].event_type == "assistant"
    assert lines[1].tool_name is None


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

    with patch(
        "syn_api.routes.conversations.get_conversation_store", return_value=mock_conversation_store
    ):
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

    with patch(
        "syn_api.routes.conversations.get_conversation_store", return_value=mock_conversation_store
    ):
        from syn_api.routes.conversations import get_conversation_metadata

        result = await get_conversation_metadata("nonexistent")

    assert isinstance(result, Ok)
    assert result.value is None
