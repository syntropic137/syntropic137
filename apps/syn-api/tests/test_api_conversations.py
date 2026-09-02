"""Tests for syn_api.routes.conversations — conversation log retrieval."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from syn_api.types import Err, ObservabilityError, Ok

# Ensure test environment for in-memory adapters
os.environ.setdefault("APP_ENVIRONMENT", "test")

pytestmark = pytest.mark.unit


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


async def _seed_session_summary(
    session_id: str, *, status: str, total_tokens: int, agent_launched: bool
) -> None:
    """Write a minimal session_summaries row directly, bypassing event replay.

    Mirrors the shape ``SessionListProjection.on_session_started`` /
    ``on_agent_launched`` / ``on_session_completed`` produce in production.
    ``agent_launched`` is required (no default) because a fixture that omits
    it silently exercises the pre-fix code path - see #1047/#1065: the write
    path can never produce a row where a session ran real work but
    ``agent_launched`` is unset, so every fixture here must set it explicitly
    to the value the corresponding real event sequence would leave behind.
    """
    from syn_api._wiring import get_projection_mgr

    mgr = get_projection_mgr()
    await mgr.store.save(
        "session_summaries",
        session_id,
        {
            "id": session_id,
            "workflow_id": "wf-1",
            "agent_type": "claude",
            "status": status,
            "total_tokens": total_tokens,
            "started_at": None,
            "completed_at": None,
            "agent_launched": agent_launched,
        },
    )


async def test_conversation_log_endpoint_reports_honest_message_when_never_started(
    mock_conversation_store,
):
    """A session that failed before the agent ever launched (agent_launched=False,
    the shape SessionLifecycleManager.complete_failure produces when it fires
    during workspace provisioning, before mark_launched() ever runs) gets an
    honest 'never started' message instead of the misleading 'not found' text
    (#1047, #1065).
    """
    from fastapi import HTTPException

    await _seed_session_summary(
        "never-started-1", status="failed", total_tokens=0, agent_launched=False
    )

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log_endpoint

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_log_endpoint("never-started-1")

    detail = exc_info.value.detail
    assert "never started" in detail.lower()
    assert "not found" not in detail.lower()


async def test_conversation_log_endpoint_keeps_not_found_when_agent_ran(
    mock_conversation_store,
):
    """A session whose agent actually launched (agent_launched=True) and then
    failed keeps the real NOT_FOUND message when its log is genuinely missing
    from storage - the fix must not mask an actual data-loss case as "never
    started".

    total_tokens=0 here is deliberate: this is the row shape the write path
    ACTUALLY produces for an agent that launched, streamed nothing (e.g.
    crashed before its first token), and then failed -
    ``SessionLifecycleManager.complete_failure`` never calls
    ``record_operation``, so total_tokens is 0 on every failure path
    regardless of how much the agent did. A fixture seeding total_tokens=500
    on a status="failed" row (the old, disproven test) is a shape production
    can never emit; agent_launched is the only real discriminator (#1047,
    #1065).
    """
    from fastapi import HTTPException

    await _seed_session_summary(
        "ran-then-failed-1", status="failed", total_tokens=0, agent_launched=True
    )

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log_endpoint

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_log_endpoint("ran-then-failed-1")

    detail = exc_info.value.detail
    assert "not found" in detail.lower()
    assert "never started" not in detail.lower()


async def test_conversation_log_endpoint_reports_pending_while_running(
    mock_conversation_store,
):
    """A session still ``running`` must never be classified as NEVER_STARTED,
    regardless of ``agent_launched`` - it hasn't reached a terminal state yet
    and may still produce a log. This is the second blocker fix (#1065): the
    original predicate (status in {failed, cancelled}) silently excluded
    "running" and fell through to the misleading generic NOT_FOUND message.
    """
    from fastapi import HTTPException

    await _seed_session_summary(
        "still-running-1", status="running", total_tokens=0, agent_launched=False
    )

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log_endpoint

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_log_endpoint("still-running-1")

    detail = exc_info.value.detail
    assert "still running" in detail.lower()
    assert "never started" not in detail.lower()


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


async def test_codex_command_execution_started_is_system_no_tool_row(mock_conversation_store):
    """An ``item.started`` command_execution renders as a plain system line.

    It must NOT produce a tool_use row - only ``item.completed`` does, so
    the same tool call never renders twice regardless of output emptiness.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.started","item":{"id":"item_2","type":"command_execution",'
        '"command":"cat one.txt","status":"in_progress"}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "system"
    assert line.tool_name is None
    assert line.content_preview is None


async def test_codex_file_change_started_is_system_no_tool_row(mock_conversation_store):
    """An ``item.started`` file_change renders as a plain system line, not a tool row."""
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.started","item":{"id":"item_1","type":"file_change",'
        '"status":"in_progress","changes":[{"path":"src/a.py","kind":"modify"}]}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "system"
    assert line.tool_name is None
    assert line.content_preview is None


async def test_codex_command_execution_started_and_completed_no_duplicate(mock_conversation_store):
    """The started/completed pair for the SAME command renders exactly ONE tool row.

    Regression guard: before this fix, both rows normalized to the same
    (event_type, tool_name, preview) triple and rendered as byte-identical
    duplicates in the transcript.
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
    assert started.event_type == "system"
    assert started.tool_name is None
    assert completed.event_type == "tool_use"
    assert completed.tool_name == "Bash"
    assert completed.content_preview == "alpha"


async def test_codex_command_execution_completed_falls_back_to_command(mock_conversation_store):
    """An ``item.completed`` with empty aggregated_output falls back to the command.

    This is the case that used to produce a duplicate row: started and
    completed both showed the bare command with no distinguishing preview.
    Now started is suppressed entirely, so there is exactly one row.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.started","item":{"id":"item_2","type":"command_execution",'
        '"command":"cat one.txt","status":"in_progress"}}',
        '{"type":"item.completed","item":{"id":"item_2","type":"command_execution",'
        '"command":"cat one.txt","aggregated_output":"","exit_code":0,'
        '"status":"completed"}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    started, completed = result.value.lines
    assert started.event_type == "system"
    assert started.tool_name is None
    assert completed.event_type == "tool_use"
    assert completed.tool_name == "Bash"
    assert completed.content_preview == "cat one.txt"


async def test_codex_file_change_maps_to_edit_tool(mock_conversation_store):
    """A codex ``file_change`` item.completed maps to the Edit tool with the changed paths."""
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


async def test_codex_file_change_started_and_completed_no_duplicate(mock_conversation_store):
    """The started/completed pair for the SAME file_change renders exactly ONE tool row.

    Regression guard for the fixture case where ``changes`` is present on
    BOTH started and completed with identical paths.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type":"item.started","item":{"id":"item_1","type":"file_change",'
        '"status":"in_progress","changes":[{"path":"src/a.py","kind":"modify"}]}}',
        '{"type":"item.completed","item":{"id":"item_1","type":"file_change",'
        '"status":"completed","changes":[{"path":"src/a.py","kind":"modify"}]}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    started, completed = result.value.lines
    assert started.event_type == "system"
    assert started.tool_name is None
    assert completed.event_type == "tool_use"
    assert completed.tool_name == "Edit"
    assert completed.content_preview == "src/a.py"


async def test_codex_real_fixture_has_no_duplicate_tool_rows(mock_conversation_store):
    """Strong regression guard: run the real recorded codex fixture through the

    full pipeline and assert no two rows share the same
    (event_type, tool_name, content_preview) triple where tool_name is set.
    This proves duplication is gone against real recorded data, not just
    hand-crafted fixtures.
    """
    import pathlib

    fixture_path = (
        pathlib.Path(__file__).parents[3]
        / "packages"
        / "syn-domain"
        / "tests"
        / "fixtures"
        / "codex"
        / "codex_exec_recording.jsonl"
    )
    raw_lines = fixture_path.read_text().splitlines()
    mock_conversation_store.retrieve_session.return_value = raw_lines

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("codex-1")

    assert isinstance(result, Ok)
    lines = result.value.lines
    assert len(lines) > 0

    tool_triples = [
        (line.event_type, line.tool_name, line.content_preview)
        for line in lines
        if line.tool_name is not None
    ]
    assert len(tool_triples) == len(set(tool_triples)), (
        f"Duplicate tool rows found in real fixture: {tool_triples}"
    )


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
