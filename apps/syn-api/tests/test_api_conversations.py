"""Tests for syn_api.routes.conversations — conversation log retrieval."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from syn_api.types import Err, ObservabilityError, Ok

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


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


# =============================================================================
# Claude nested tool blocks (#1067)
#
# The lines marked "verbatim" below are copied unmodified from the recorded
# session
# lib/agentic-primitives/.../recordings/v2.0.74_claude-sonnet-4-5_git-status.jsonl
# (a matched tool_use / tool_result pair - note the shared tool_use_id). They
# are inlined rather than read from the submodule so these tests do not depend
# on a submodule checkout. Claude puts the tool name at
# ``message.content[].name`` and NOTHING at the top level, which is why the
# generic extractor rendered every one of these rows as an em dash.
# =============================================================================

_CLAUDE_TOOL_USE_LINE = (  # verbatim
    '{"type": "assistant", "message": {"model": "claude-sonnet-4-5-20250929",'
    ' "id": "msg_01DNPo5rXDrdLzG9L1kwRb9V", "type": "message", "role": "assistant",'
    ' "content": [{"type": "tool_use", "id": "toolu_01CdeRemHbNPyT5JosrR89Z6",'
    ' "name": "Bash", "input": {"command": "git status",'
    ' "description": "Check git repository status"}}], "stop_reason": null},'
    ' "session_id": "292ca99e-3884-420e-b533-788c09885348"}'
)

_CLAUDE_TOOL_RESULT_LINE = (  # verbatim
    '{"type": "user", "message": {"role": "user", "content": [{"type": "tool_result",'
    ' "content": "Exit code 128\\nfatal: not a git repository (or any of the parent'
    ' directories): .git", "is_error": true,'
    ' "tool_use_id": "toolu_01CdeRemHbNPyT5JosrR89Z6"}]},'
    ' "session_id": "292ca99e-3884-420e-b533-788c09885348"}'
)


async def test_claude_tool_use_surfaces_tool_name_and_command(mock_conversation_store):
    """A claude ``tool_use`` line reports the tool it called and what it ran.

    "Bash" and "git status" exist ONLY inside ``message.content[0]`` - there is
    no top-level ``name``/``tool_name``/``content`` on the line - so neither
    value can be produced by the top-level lookup this replaced.
    """
    mock_conversation_store.retrieve_session.return_value = [_CLAUDE_TOOL_USE_LINE]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.tool_name == "Bash"
    assert line.content_preview == "git status"


async def test_claude_tool_result_surfaces_output_and_marks_error(mock_conversation_store):
    """A claude ``tool_result`` line previews its output and flags failure.

    The tool name is deliberately absent: the line carries only a
    ``tool_use_id``, so naming the tool here would be a guess.
    """
    mock_conversation_store.retrieve_session.return_value = [_CLAUDE_TOOL_RESULT_LINE]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.tool_name is None
    assert line.content_preview is not None
    assert line.content_preview.startswith("Error: ")
    assert "fatal: not a git repository" in line.content_preview


async def test_claude_tool_use_previews_unrecognized_input_shape(mock_conversation_store):
    """A tool whose input has no command/path/pattern key still previews.

    TodoWrite's input is ``{"todos": [...]}``. Falling back to the serialized
    input keeps the row informative for tool shapes that did not exist when
    this code was written, instead of blanking on every unfamiliar tool.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"content": [{"type": "tool_use",'
        ' "id": "toolu_9", "name": "TodoWrite", "input": {"todos":'
        ' [{"content": "Run the h2o script", "status": "in_progress"}]}}]}}'
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.tool_name == "TodoWrite"
    assert line.content_preview is not None
    assert "Run the h2o script" in line.content_preview


async def test_preview_is_always_single_line(mock_conversation_store):
    """No preview contains a newline, on either harness.

    Every preview lands in a one-line cell (the CLI's table column, the
    dashboard's ``truncate`` row), so a raw newline breaks the layout of
    whatever renders it. Both a claude tool result and a codex command
    output carry real multi-line shell output here.
    """
    mock_conversation_store.retrieve_session.return_value = [
        _CLAUDE_TOOL_RESULT_LINE,
        '{"type":"item.completed","item":{"id":"item_2","type":"command_execution",'
        '"command":"ls","aggregated_output":"one.txt\\ntwo.txt\\n","exit_code":0,'
        '"status":"completed"}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("mixed-1")

    assert isinstance(result, Ok)
    previews = [line.content_preview for line in result.value.lines]
    assert all(p is not None for p in previews)
    for preview in previews:
        assert "\n" not in preview, f"preview leaks a newline into a one-line cell: {preview!r}"
    # The codex row still shows both files - single-lining must not truncate.
    assert previews[1] == "one.txt two.txt"


async def test_tool_fields_survive_the_http_response_hop(mock_conversation_store):
    """The endpoint's response model carries tool_name/content_preview through.

    ``get_conversation_log_endpoint`` rebuilds every line field-by-field into
    ``ConversationLineResponse``. That is the object the CLI and dashboard
    actually receive, and a field dropped there is invisible to every test
    that stops at ``ConversationLine``.
    """
    from unittest.mock import MagicMock

    mock_conversation_store.retrieve_session.return_value = [_CLAUDE_TOOL_USE_LINE]

    with (
        _patch_store(mock_conversation_store),
        patch("syn_api._wiring.get_projection_mgr", new=MagicMock()),
        patch(
            "syn_api.prefix_resolver.resolve_or_raise",
            new=AsyncMock(return_value="claude-1"),
        ),
    ):
        from syn_api.routes.conversations import get_conversation_log_endpoint

        response = await get_conversation_log_endpoint("claude-1")

    line = response.lines[0]
    assert line.tool_name == "Bash"
    assert line.content_preview == "git status"


async def test_claude_result_line_previews_its_summary(mock_conversation_store):
    """Claude's final ``result`` line previews the summary it carries.

    ``result`` is a plain string here, which is the shape the real CLI emits;
    only the ``{"output": ...}`` dict form used to be read, so the closing
    line of every claude transcript rendered as an em dash.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "result", "subtype": "success", "is_error": false,'
        ' "result": "The current directory is not a git repository.",'
        ' "session_id": "292ca99e-3884-420e-b533-788c09885348"}'
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "result"
    assert line.content_preview == "The current directory is not a git repository."
