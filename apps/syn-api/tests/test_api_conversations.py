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


# The separator ``_extract_claude_tool_fields`` joins per-block values with:
# a space, U+00A6 BROKEN BAR, a space. Duplicated here deliberately - importing
# the private constant would make every assertion below agree with the
# implementation by construction, including when the implementation is wrong.
#
# Spelled as an escape, not as the glyph, because the whole point of this
# character is that it is NOT the ASCII pipe, and in many fonts the two are
# almost indistinguishable.
_SEP_CHAR = "\u00a6"
_SEP = f" {_SEP_CHAR} "

# A pipe is ordinary CONTENT in these fields (they carry shell commands), and
# must reach the reader untouched. Bound separately from ``_SEP`` so a test can
# say which of the two it means.
_PIPE_IN_CONTENT = " | "


def _as_segment(value: str) -> str:
    """One block value as it is expected to RENDER inside a joined field.

    The other half of the separator contract, restated here rather than
    imported for the same reason ``_SEP`` is: a block's own text may not carry
    the separator character, so an occurrence of it is displayed as an ordinary
    pipe. Applies to any value that reaches a column - a preview or a tool
    name, which an MCP server is free to choose.
    """
    return value.replace(_SEP_CHAR, "|")


_TOOL_BLOCK_TYPES = ("tool_use", "tool_result")


def _assert_every_tool_block_is_represented(lines) -> int:
    """Assert every raw tool block reaches its OWN slot in the line's fields.

    Returns the number of tool blocks checked, so callers can sanity-check
    that their fixture actually contains the shape.

    Two properties, and the second is the one that pins the #1072 review's
    positional-desync finding:

    1. Every raw ``tool_use`` has a non-null name, and that name is rendered
       at that block's OWN index in ``tool_name`` - not merely present
       somewhere in it. Membership plus a count would let two blocks swap.
    2. A rendered column carries exactly one segment per TOOL BLOCK, in block
       order. That holds for BOTH columns, so an index into one is an index
       into the other, and a block that contributes to one column but not the
       other cannot pull every later segment of the shorter column up by one.
       A column collapses to None only when no block contributed to it at all.

    Written to survive both of the #1067 review's checks on property tests:
    the assertions reference the loop variable (each block's own name at its
    own index, so deleting the loop changes the meaning), and breaking the
    property for the SECOND block only fails it - a dropped or shifted later
    block changes that column's segment count or puts the wrong value at that
    index.
    """
    import json as _json

    checked = 0
    for line in lines:
        data = _json.loads(line.raw)
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue

        blocks = [item for item in content if isinstance(item, dict)]
        tool_blocks = [item for item in blocks if item.get("type") in _TOOL_BLOCK_TYPES]
        if not tool_blocks:
            # No tool block on this line: it never reaches the claude tool
            # extractor at all, so it has nothing to say about the invariant.
            continue

        tool_uses = [item for item in tool_blocks if item.get("type") == "tool_use"]
        tool_results = [item for item in tool_blocks if item.get("type") == "tool_result"]

        if tool_uses:
            assert line.tool_name is not None, (
                f"Line {line.line_number} has {len(tool_uses)} tool_use block(s) "
                f"but rendered no tool_name at all: {line.raw}"
            )
        # Only results that HAVE output. A command that printed nothing yields
        # no preview, and a line of nothing but such results collapses the
        # whole column to None - the module's documented behaviour, and a real
        # recorded shape (``context-tracking.jsonl`` line 13 is a tool_result
        # with ``content: ""``). Asserting non-null for every result would fail
        # on correct output; #1067's "blank tool row" defect was blocks that
        # HAD content and rendered nothing, which is what this still catches.
        results_with_output = [
            item for item in tool_results if str(item.get("content") or "").strip()
        ]
        if results_with_output:
            assert line.content_preview is not None, (
                f"Line {line.line_number} carries {len(results_with_output)} tool_result "
                f"block(s) with output but rendered no preview: {line.raw}"
            )

        rendered_names = line.tool_name.split(_SEP) if line.tool_name is not None else []
        rendered_previews = (
            line.content_preview.split(_SEP) if line.content_preview is not None else []
        )

        # One segment per tool block, on whichever columns are present. This is
        # what catches both "only the first block survives" (too few segments)
        # and "the two columns were filtered independently" (the columns
        # disagree with each other and with the block count).
        for field, rendered in (
            ("tool_name", rendered_names),
            ("content_preview", rendered_previews),
        ):
            if not rendered:
                continue
            assert len(rendered) == len(tool_blocks), (
                f"Line {line.line_number} has {len(tool_blocks)} tool block(s) but "
                f"{field} renders {len(rendered)} segment(s) "
                f"({line.tool_name!r} / {line.content_preview!r}) - a block is "
                f"missing a slot, so the two columns no longer line up: {line.raw}"
            )

        for index, item in enumerate(tool_blocks):
            checked += 1
            if item.get("type") != "tool_use":
                continue
            name = item.get("name")
            assert isinstance(name, str) and name, (
                f"Line {line.line_number} has a tool_use block with no usable "
                f"name, so the invariant cannot hold: {line.raw}"
            )
            assert rendered_names[index] == _as_segment(name), (
                f"Line {line.line_number} has a tool_use for {name!r} at block "
                f"index {index}, but the rendered tool_name has "
                f"{rendered_names[index]!r} there ({line.tool_name!r}): {line.raw}"
            )

    return checked


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


async def test_claude_tool_use_bash_surfaces_name_and_command(mock_conversation_store):
    """A real Claude Code ``tool_use`` line (Bash) surfaces its name and command.

    Raw line taken from a recorded session (agentic-primitives
    ``v2.0.74_claude-sonnet-4-5_multi-tool.jsonl``) with the ``usage`` object
    trimmed to ``input_tokens`` - the shape under test is unaffected by the
    token fields. This is issue #1067's premise: the nested
    ``message.content[].tool_use`` shape, not the flattened synthetic shape
    used by the older tests in this file.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"model": "claude-sonnet-4-5-20250929", '
        '"id": "msg_01K5vXsmzoYvC8JpXVbnDnpb", "type": "message", "role": "assistant", '
        '"content": [{"type": "tool_use", "id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT", '
        '"name": "Bash", "input": {"command": "pytest --version", '
        '"description": "Check if pytest is installed"}}], "stop_reason": null, '
        '"stop_sequence": null, "usage": {"input_tokens": 2}, "context_management": null}, '
        '"parent_tool_use_id": null, "session_id": "62f1c87d-c98b-4053-aab1-766804bdd1db", '
        '"uuid": "df092cdf-514d-4fcc-b578-9ea162850544", "_offset_ms": 0}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "tool_use"
    assert line.tool_name == "Bash"
    assert line.content_preview == "pytest --version"


async def test_claude_tool_use_read_surfaces_file_path(mock_conversation_store):
    """A real Claude Code ``tool_use`` line (Read) surfaces its ``file_path``.

    Raw line from ``v2.0.74_claude-sonnet-4-5_file-read.jsonl``, with the
    ``usage`` object trimmed to ``input_tokens``.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"model": "claude-sonnet-4-5-20250929", '
        '"id": "msg_016xBPSbaR7QVRzPQ4dVDBrw", "type": "message", "role": "assistant", '
        '"content": [{"type": "tool_use", "id": "toolu_018iVpEgCDjX5CQofmdEMNgX", '
        '"name": "Read", "input": {"file_path": "/workspace/pyproject.toml"}}], '
        '"stop_reason": null, "stop_sequence": null, "usage": {"input_tokens": 2}, '
        '"context_management": null}, "parent_tool_use_id": null, '
        '"session_id": "221751c1-866a-467d-8adb-c2616eee0748", '
        '"uuid": "b0351ec9-3576-4fcb-9625-10e00875f1be", "_offset_ms": 0}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "tool_use"
    assert line.tool_name == "Read"
    assert line.content_preview == "/workspace/pyproject.toml"


async def test_claude_tool_result_error_is_flagged(mock_conversation_store):
    """A real Claude Code ``tool_result`` with ``is_error: true`` is flagged.

    Raw line verbatim from ``v2.0.74_claude-sonnet-4-5_multi-tool.jsonl`` -
    the pytest command was denied approval.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", '
        '"content": "This command requires approval", "is_error": true, '
        '"tool_use_id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT"}]}, "parent_tool_use_id": null, '
        '"session_id": "62f1c87d-c98b-4053-aab1-766804bdd1db", '
        '"uuid": "8ece95af-75a0-4b1f-a42c-078b0327960e", '
        '"tool_use_result": "Error: This command requires approval", "_offset_ms": 0}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "user"
    assert line.content_preview == "[error] This command requires approval"


async def test_claude_tool_result_success_shows_first_line(mock_conversation_store):
    """A real Claude Code ``tool_result`` without an error shows its output, unflagged.

    Raw line verbatim from ``v2.0.74_claude-sonnet-4-5_multi-tool.jsonl``.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "user", "message": {"role": "user", "content": [{"tool_use_id": '
        '"toolu_01EcpwqYwJdp8gooTES6smmV", "type": "tool_result", '
        '"content": "No files found"}]}, "parent_tool_use_id": null, '
        '"session_id": "62f1c87d-c98b-4053-aab1-766804bdd1db", '
        '"uuid": "02830228-ea7a-47b6-88ee-abec55322aa0", '
        '"tool_use_result": {"filenames": [], "durationMs": 7, "numFiles": 0, '
        '"truncated": false}, "_offset_ms": 0}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "user"
    assert line.content_preview == "No files found"


async def test_claude_tool_result_list_content_blocks_use_first_line(mock_conversation_store):
    """A ``tool_result`` whose ``content`` is a list of text blocks (subagent

    results) is flattened and only the first line of the first block is
    shown. Raw line from
    ``v2.0.76_claude-haiku-4-5_subagent-concurrent.jsonl`` (where the first
    text block itself spans multiple lines), with the recording's sibling
    ``tool_use_result`` key dropped - the extractor reads ``message`` only.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "user", "message": {"role": "user", "content": [{"tool_use_id": '
        '"toolu_01XxMwNeHP7xCrM8bj5UickN", "type": "tool_result", "content": '
        '[{"type": "text", "text": "The command `whoami` returned: **agent**\\n\\n'
        'This indicates that the current user is \\"agent\\"."}, {"type": "text", '
        '"text": "agentId: a775cd0 (for resuming to continue this agent\'s work if '
        'needed)"}]}]}, "parent_tool_use_id": null, '
        '"session_id": "9c4d2e8f-9fc2-400d-a4f3-60bed3701453", '
        '"uuid": "70b03589-1849-4baf-9ee4-5b9467f16628", "_offset_ms": 5152}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.content_preview == "The command `whoami` returned: **agent**"


async def test_claude_system_init_line_has_no_tool_row(mock_conversation_store):
    """A real ``system``/``init`` line (session banner) has no tool_name/preview.

    Raw line from ``v2.0.74_claude-sonnet-4-5_multi-tool.jsonl`` with the
    banner's long inventory fields (``tools``, ``slash_commands``, ``agents``,
    ``skills``, ``plugins``, ``output_style``) shortened or dropped; none of
    them are read by the extractor. Regression guard: it must not be
    misidentified as a tool line by the new claude tool extractor.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "system", "subtype": "init", "cwd": "/workspace", '
        '"session_id": "62f1c87d-c98b-4053-aab1-766804bdd1db", '
        '"tools": ["Task", "Bash", "Read", "Edit", "Write"], "mcp_servers": [], '
        '"model": "claude-sonnet-4-5-20250929", "permissionMode": "default", '
        '"apiKeySource": "ANTHROPIC_API_KEY", "claude_code_version": "2.0.74", '
        '"uuid": "e45d5962-f6b8-4c2f-9010-141f6e77e84e", "_offset_ms": 0}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "system"
    assert line.tool_name is None
    assert line.content_preview is None


async def test_unrecognized_top_level_type_does_not_crash(mock_conversation_store):
    """A line whose top-level ``type`` is neither claude's nor codex's vocabulary

    (e.g. an Anthropic API ``rate_limit_event`` passthrough) must not crash
    the request - it renders as a plain line with that type and no tool
    fields, same as before this change.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "rate_limit_event", "retry_after": 5}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "rate_limit_event"
    assert line.tool_name is None


async def test_claude_real_recorded_multi_tool_transcript_has_no_blank_tool_rows(
    mock_conversation_store,
):
    """End-to-end regression guard against issue #1067 using a real recording.

    Runs the full, unmodified ``v2.0.74_claude-sonnet-4-5_multi-tool.jsonl``
    recording (agentic-primitives fixture) through the pipeline and asserts
    every tool_use/tool_result line - not just hand-picked ones - gets a
    non-null tool_name or content_preview. Before this fix, all of these
    rendered as (None, None): the exact defect from the issue.
    """
    import pathlib

    fixture_path = (
        pathlib.Path(__file__).parents[3]
        / "lib"
        / "agentic-primitives"
        / "providers"
        / "workspaces"
        / "claude-cli"
        / "fixtures"
        / "recordings"
        / "v2.0.74_claude-sonnet-4-5_multi-tool.jsonl"
    )
    raw_lines = [line for line in fixture_path.read_text().splitlines() if line.strip()]
    # First line is a ``_recording`` metadata envelope the real store never
    # persists (added by the recorder, not the harness) - drop it like the
    # playback tooling does.
    raw_lines = [line for line in raw_lines if not line.startswith('{"_recording"')]
    mock_conversation_store.retrieve_session.return_value = raw_lines

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    lines = result.value.lines
    assert len(lines) > 0

    # Sanity check the recording actually exercises the shape under test.
    assert _assert_every_tool_block_is_represented(lines) >= 4


# Claude emits parallel tool calls as several ``tool_use`` blocks inside ONE
# ``message.content[]`` list, and their results as several ``tool_result``
# blocks inside one user message. No recording checked into this repo or its
# submodules contains that shape - every recorded line carries exactly one
# content block, because the CLI versions that produced them split each block
# onto its own stream-json line. The lines below are therefore CONSTRUCTED,
# not recorded: real content blocks (including their real ``toolu_`` ids) are
# lifted verbatim from ``v2.0.74_claude-sonnet-4-5_multi-tool.jsonl`` lines
# 3-7 and merged into single messages, with an obviously-synthetic ``uuid`` so
# nobody mistakes these for a recording. The merged shape is the one
# ``agentic_isolation``'s claude_cli ``event_parser`` already handles by
# iterating every block, so it is the format's shape, not an invention here.
_CONSTRUCTED_PARALLEL_TOOL_USE_LINE = (
    '{"type": "assistant", "message": {"model": "claude-sonnet-4-5-20250929", '
    '"id": "msg_01K5vXsmzoYvC8JpXVbnDnpb", "type": "message", "role": "assistant", '
    '"content": [{"type": "text", "text": "I\'ll check if pytest is installed and '
    'then look for conftest.py."}, '
    '{"type": "tool_use", "id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT", "name": "Bash", '
    '"input": {"command": "pytest --version", "description": "Check if pytest is '
    'installed"}}, '
    '{"type": "tool_use", "id": "toolu_01EcpwqYwJdp8gooTES6smmV", "name": "Glob", '
    '"input": {"pattern": "**/conftest.py"}}], '
    '"stop_reason": null, "stop_sequence": null, "usage": {"input_tokens": 2}}, '
    '"parent_tool_use_id": null, "session_id": "62f1c87d-c98b-4053-aab1-766804bdd1db", '
    '"uuid": "00000000-0000-0000-0000-000000000001"}'
)

_CONSTRUCTED_PARALLEL_TOOL_RESULT_LINE = (
    '{"type": "user", "message": {"role": "user", "content": ['
    '{"type": "tool_result", "content": "This command requires approval", '
    '"is_error": true, "tool_use_id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT"}, '
    '{"tool_use_id": "toolu_01EcpwqYwJdp8gooTES6smmV", "type": "tool_result", '
    '"content": "No files found"}]}, '
    '"parent_tool_use_id": null, "session_id": "62f1c87d-c98b-4053-aab1-766804bdd1db", '
    '"uuid": "00000000-0000-0000-0000-000000000002"}'
)


async def test_claude_parallel_tool_use_blocks_all_reach_the_line(
    mock_conversation_store,
):
    """Both tool_use blocks on one assistant line are rendered, not just the first.

    Guards the #1067 review blocker: ``_extract_claude_tool_fields`` used to
    return on the first tool block, so the second parallel call vanished from
    the transcript. ``Glob``/``**/conftest.py`` cannot appear in either field
    unless every block is scanned - before the fix this line rendered
    ``("Bash", "pytest --version")`` and the Glob call was gone.

    Asserted through ``get_conversation_log`` (the consumer), not the private
    extractor, so a value dropped between extractor and ``ConversationLine``
    would still fail this.
    """
    mock_conversation_store.retrieve_session.return_value = [
        _CONSTRUCTED_PARALLEL_TOOL_USE_LINE,
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "tool_use"
    assert line.tool_name == f"Bash{_SEP}Glob"
    assert line.content_preview == f"pytest --version{_SEP}**/conftest.py"
    _assert_every_tool_block_is_represented(result.value.lines)


async def test_claude_parallel_tool_results_all_reach_the_line(
    mock_conversation_store,
):
    """Both tool_result blocks on one user line are previewed, not just the first.

    The second result (``No files found``) is only reachable by scanning past
    the first block; the error flag on the first is preserved alongside it.
    """
    mock_conversation_store.retrieve_session.return_value = [
        _CONSTRUCTED_PARALLEL_TOOL_RESULT_LINE,
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    # Only tool_results on the line, so it keeps its own top-level type.
    assert line.event_type == "user"
    assert line.tool_name is None
    assert line.content_preview == (f"[error] This command requires approval{_SEP}No files found")
    _assert_every_tool_block_is_represented(result.value.lines)


async def test_claude_repeated_tool_name_renders_once_per_call(
    mock_conversation_store,
):
    """Two parallel calls to the SAME tool render two names, not one.

    The membership half of the invariant cannot see this case - ``"Bash" in
    ["Bash"]`` holds however many Bash blocks were dropped - so the count half
    is what catches it. Without the fix this renders ``"Bash"`` and only the
    first command.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        '{"type": "tool_use", "id": "toolu_01aaaaaaaaaaaaaaaaaaaaaa", "name": "Bash", '
        '"input": {"command": "git rev-parse HEAD"}}, '
        '{"type": "tool_use", "id": "toolu_01bbbbbbbbbbbbbbbbbbbbbb", "name": "Bash", '
        '"input": {"command": "git status --short"}}]}, '
        '"uuid": "00000000-0000-0000-0000-000000000003"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.tool_name == f"Bash{_SEP}Bash"
    assert line.content_preview == f"git rev-parse HEAD{_SEP}git status --short"
    _assert_every_tool_block_is_represented(result.value.lines)


# A middle block that yields a NAME but no PREVIEW. ``TodoWrite`` is the real,
# common tool with that shape: its input's only key is ``todos``, which is not
# in ``_CLAUDE_TOOL_INPUT_KEYS``, so it can never produce a preview. The Bash
# and Glob blocks are lifted verbatim (real ``toolu_`` ids and all) from
# ``v2.0.74_claude-sonnet-4-5_multi-tool.jsonl`` lines 4-5; the TodoWrite block
# keeps its real id from ``v2.1.29_claude-sonnet-4-5_multi-model-usage`` line 4
# with its ``todos`` array trimmed to one entry - the entries' contents are
# irrelevant here, the absence of any preview-yielding key is the point. The
# merge into one message is CONSTRUCTED, as documented above.
_CONSTRUCTED_PREVIEWLESS_MIDDLE_BLOCK_LINE = (
    '{"type": "assistant", "message": {"role": "assistant", "content": ['
    '{"type": "tool_use", "id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT", "name": "Bash", '
    '"input": {"command": "pytest --version", "description": "Check if pytest is '
    'installed"}}, '
    '{"type": "tool_use", "id": "toolu_0165StoiZTi2jCHfh3GDaohs", "name": "TodoWrite", '
    '"input": {"todos": [{"content": "Write Python script h2o_lightyear.py", '
    '"status": "in_progress", "activeForm": "Writing Python script h2o_lightyear.py"}]}}, '
    '{"type": "tool_use", "id": "toolu_01EcpwqYwJdp8gooTES6smmV", "name": "Glob", '
    '"input": {"pattern": "**/conftest.py"}}]}, '
    '"uuid": "00000000-0000-0000-0000-000000000005"}'
)

# The same asymmetry in the other column and the other block kind: a
# ``tool_result`` whose output is blank (a command that printed nothing)
# yields no preview, while every ``tool_result`` yields no name. Ids are the
# real ones from ``v2.0.74_claude-sonnet-4-5_multi-tool.jsonl`` lines 6-7.
_CONSTRUCTED_PREVIEWLESS_FIRST_RESULT_LINE = (
    '{"type": "user", "message": {"role": "user", "content": ['
    '{"type": "tool_result", "tool_use_id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT", '
    '"content": ""}, '
    '{"type": "tool_result", "tool_use_id": "toolu_01EcpwqYwJdp8gooTES6smmV", '
    '"content": "No files found"}]}, '
    '"uuid": "00000000-0000-0000-0000-000000000006"}'
)


async def test_claude_previewless_middle_block_keeps_later_previews_on_their_own_tool(
    mock_conversation_store,
):
    """A block with a name but no preview must not shift later previews up one.

    The #1072 review's finding. ``tool_name`` and ``content_preview`` used to
    be accumulated as two independently-filtered lists with no shared index, so
    ``TodoWrite`` (a name, never a preview) took a slot in one column and none
    in the other. This exact line then rendered:

        tool_name       "Bash | TodoWrite | Glob"
        content_preview "pytest --version | **/conftest.py"

    Glob's ``**/conftest.py`` sat at index 1, under ``TodoWrite`` - active
    misattribution, not a missing value, and invisible to a reader of the two
    joined strings. Asserted through ``get_conversation_log`` (the consumer),
    not the private extractor, so a value dropped on the way to
    ``ConversationLine`` would still fail this.
    """
    mock_conversation_store.retrieve_session.return_value = [
        _CONSTRUCTED_PREVIEWLESS_MIDDLE_BLOCK_LINE,
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]

    names = line.tool_name.split(_SEP)
    previews = line.content_preview.split(_SEP)
    assert names == ["Bash", "TodoWrite", "Glob"]
    # Three blocks, so three preview slots - the middle one empty because
    # TodoWrite has no preview-yielding input key. Two slots is the bug.
    assert len(previews) == len(names) == 3, (
        f"columns disagree: {line.tool_name!r} / {line.content_preview!r}"
    )
    assert previews[names.index("TodoWrite")] == ""
    assert previews[names.index("Glob")] == "**/conftest.py"
    assert previews[names.index("Bash")] == "pytest --version"
    _assert_every_tool_block_is_represented(result.value.lines)


async def test_claude_previewless_first_result_keeps_later_previews_in_place(
    mock_conversation_store,
):
    """A blank tool_result must hold its own preview slot, not vanish from it.

    The mirror of the case above, in the preview column: the first result is
    the output of a command that printed nothing, so it yields no preview.
    Before the fix this line rendered ``content_preview="No files found"`` -
    one segment for two result blocks, so the second result's output read as
    the FIRST result's.
    """
    mock_conversation_store.retrieve_session.return_value = [
        _CONSTRUCTED_PREVIEWLESS_FIRST_RESULT_LINE,
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]

    # Only tool_results on the line, so no block contributes a name at all and
    # the column collapses to None rather than to a row of bare separators.
    assert line.tool_name is None
    previews = line.content_preview.split(_SEP)
    assert previews == ["", "No files found"], (
        f"blank first result lost its slot: {line.content_preview!r}"
    )
    _assert_every_tool_block_is_represented(result.value.lines)


async def test_claude_tool_use_and_result_on_one_line_keep_matching_slot_counts(
    mock_conversation_store,
):
    """Both columns split to the same length even when block kinds are mixed.

    A ``tool_result`` never yields a name, so on a line mixing kinds the name
    column used to be shorter than the preview column and the two could not be
    read side by side at all. Now every block holds a slot in both.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        '{"type": "tool_use", "id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT", "name": "Bash", '
        '"input": {"command": "pytest --version"}}, '
        '{"type": "tool_result", "tool_use_id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT", '
        '"content": "pytest 8.3.4"}]}, '
        '"uuid": "00000000-0000-0000-0000-000000000007"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]

    names = line.tool_name.split(_SEP)
    previews = line.content_preview.split(_SEP)
    assert len(names) == len(previews) == 2, (
        f"columns disagree: {line.tool_name!r} / {line.content_preview!r}"
    )
    assert names == ["Bash", ""]
    assert previews == ["pytest --version", "pytest 8.3.4"]
    _assert_every_tool_block_is_represented(result.value.lines)


async def test_claude_single_tool_block_line_is_unchanged_by_the_join(
    mock_conversation_store,
):
    """The one-block shape every real recording actually has gains no separator.

    Every line in every recording in this repo has exactly one content block,
    so this is the case that must not regress: no trailing separator, no
    change to the values.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        '{"type": "tool_use", "id": "toolu_01EcpwqYwJdp8gooTES6smmV", "name": "Glob", '
        '"input": {"pattern": "**/conftest.py"}}]}, '
        '"uuid": "00000000-0000-0000-0000-000000000004"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.tool_name == "Glob"
    assert line.content_preview == "**/conftest.py"


# The #1072 review's reproduction, verbatim. Three parallel calls where the
# FIRST one's command contains a shell pipe: ``Bash`` runs a pipeline,
# ``TodoWrite`` has no preview-yielding input key at all, ``Glob`` has one.
# With the ASCII pipe as the field separator this rendered
# ``'Bash | TodoWrite | Glob'`` against
# ``'find . -name *.py | head -30 |  | **/conftest.py'`` - three names against
# FOUR previews, so a reader splitting both columns paired ``TodoWrite`` with
# ``head -30`` (which is Bash's) and ``Glob`` with nothing.
_CONSTRUCTED_PIPED_COMMAND_LINE = (
    '{"type": "assistant", "message": {"role": "assistant", "content": ['
    '{"type": "tool_use", "id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT", "name": "Bash", '
    '"input": {"command": "find . -name *.py | head -30"}}, '
    '{"type": "tool_use", "id": "toolu_01aaaaaaaaaaaaaaaaaaaaaa", "name": "TodoWrite", '
    '"input": {"todos": []}}, '
    '{"type": "tool_use", "id": "toolu_01EcpwqYwJdp8gooTES6smmV", "name": "Glob", '
    '"input": {"pattern": "**/conftest.py"}}]}, '
    '"uuid": "00000000-0000-0000-0000-000000000009"}'
)


async def test_claude_pipe_in_a_command_cannot_forge_a_block_boundary(
    mock_conversation_store,
):
    """A shell pipe in a command must not manufacture a fourth preview segment.

    The columns are aligned per block, but that alignment was only readable if
    no block's own text could spell the separator - and with the separator
    spelled ``" | "``, any piped shell command did. Three blocks rendered four
    preview segments and the pairing was wrong from the pipe onwards.

    The command is asserted back byte-for-byte on purpose: the fix must make
    the boundary unforgeable WITHOUT rewriting the pipe, because a pipeline is
    the content a reader of this column came to read.
    """
    mock_conversation_store.retrieve_session.return_value = [
        _CONSTRUCTED_PIPED_COMMAND_LINE,
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]

    names = line.tool_name.split(_SEP)
    previews = line.content_preview.split(_SEP)
    assert len(names) == len(previews) == 3, (
        f"a pipe in the command forged a segment: {line.tool_name!r} / {line.content_preview!r}"
    )
    assert names == ["Bash", "TodoWrite", "Glob"]
    assert previews == [f"find . -name *.py{_PIPE_IN_CONTENT}head -30", "", "**/conftest.py"]
    _assert_every_tool_block_is_represented(result.value.lines)


async def test_claude_preview_truncated_onto_a_pipe_keeps_the_next_block_intact(
    mock_conversation_store,
):
    """Truncation landing on a pipe must not corrupt the FOLLOWING block.

    The second, quieter half of the #1072 review's finding, and the reason the
    guarantee belongs at the join rather than inside the preview builders: a
    preview is cut to ``_TOOL_PREVIEW_LEN`` characters, and a cut can land
    anywhere. When it landed just after a pipe, the trailing ``" |"`` met the
    joined ``" | "`` and the NEXT block's preview came back as ``"| /z.py"``.
    The segment count stayed right, so the file's own invariant helper could
    not see it - only reading the value back can.
    """
    # 98 characters, then " |" - so the 100-character cut ends on a pipe.
    command = ("a" * 98) + " | echo done"
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        '{"type": "tool_use", "id": "toolu_01cccccccccccccccccccccc", "name": "Bash", '
        f'"input": {{"command": "{command}"}}}}, '
        '{"type": "tool_use", "id": "toolu_01dddddddddddddddddddddd", "name": "Read", '
        '"input": {"file_path": "/z.py"}}]}, '
        '"uuid": "00000000-0000-0000-0000-000000000010"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]

    names = line.tool_name.split(_SEP)
    previews = line.content_preview.split(_SEP)
    assert names == ["Bash", "Read"]
    assert len(previews) == 2, f"truncation split a block: {line.content_preview!r}"
    # Read's preview, not "| /z.py" with the truncated pipe glued onto it.
    assert previews[1] == "/z.py", (
        f"the cut on the previous block corrupted this one: {previews[1]!r}"
    )
    assert previews[0] == ("a" * 98) + " |"


async def test_claude_pipe_in_tool_result_output_cannot_forge_a_boundary(
    mock_conversation_store,
):
    """The same guarantee on the result side, which the review flagged untested.

    ``_claude_tool_result_preview`` renders command OUTPUT, where a pipe is at
    least as ordinary as in a command - a table row, a `ps` line, a log format.
    The review reached this hop by symmetry with the tool_use one rather than
    by measuring it; this pins it directly.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "user", "message": {"role": "user", "content": ['
        '{"type": "tool_result", "tool_use_id": "toolu_01cccccccccccccccccccccc", '
        '"content": "PID | COMMAND"}, '
        '{"type": "tool_result", "tool_use_id": "toolu_01dddddddddddddddddddddd", '
        '"content": "ok"}]}, '
        '"uuid": "00000000-0000-0000-0000-000000000011"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]

    previews = line.content_preview.split(_SEP)
    assert len(previews) == 2, f"the output's pipe forged a segment: {line.content_preview!r}"
    assert previews == [f"PID{_PIPE_IN_CONTENT}COMMAND", "ok"]
    _assert_every_tool_block_is_represented(result.value.lines)


async def test_claude_separator_character_in_content_is_rewritten_not_joined(
    mock_conversation_store,
):
    """Content that spells the separator itself is displayed, never structural.

    The other half of the guarantee, and the one that survives changing which
    character carries the structure: whatever that character is, a block's own
    text may not contain it. Exercised on BOTH sources that feed a column - a
    tool NAME (an MCP server chooses those, and nothing constrains them) and a
    preview - because the fix lives at the join and therefore has to hold for
    every source, not just the two preview builders the review named.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        '{"type": "tool_use", "id": "toolu_01eeeeeeeeeeeeeeeeeeeeee", '
        f'"name": "mcp__odd{_SEP_CHAR}server__run", '
        f'"input": {{"command": "echo a {_SEP_CHAR} b"}}}}, '
        '{"type": "tool_use", "id": "toolu_01ffffffffffffffffffffff", "name": "Read", '
        '"input": {"file_path": "/z.py"}}]}, '
        '"uuid": "00000000-0000-0000-0000-000000000012"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]

    names = line.tool_name.split(_SEP)
    previews = line.content_preview.split(_SEP)
    assert len(names) == len(previews) == 2, (
        f"content forged a boundary: {line.tool_name!r} / {line.content_preview!r}"
    )
    # Rewritten to an ordinary pipe, which is what the reader sees; the point
    # is that no segment anywhere carries the separator character.
    assert names == ["mcp__odd|server__run", "Read"]
    assert previews == ["echo a | b", "/z.py"]
    assert _SEP_CHAR not in "".join(names + previews)
    _assert_every_tool_block_is_represented(result.value.lines)


async def test_claude_separator_in_second_block_cannot_forge_a_boundary(
    mock_conversation_store,
):
    """Every value is sanitized, including values after index zero.

    The second block carries the structural character in both columns.  This
    specifically guards against sanitizing only ``values[0]`` in
    ``_join_column``: that mutation leaves the first block looking correct but
    lets the second block forge extra segments.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        '{"type": "tool_use", "id": "toolu_01aaaaaaaaaaaaaaaaaaaaaa", '
        '"name": "Read", "input": {"file_path": "/a.py"}}, '
        '{"type": "tool_use", "id": "toolu_01bbbbbbbbbbbbbbbbbbbbbb", '
        f'"name": "Read {_SEP_CHAR} Bash", '
        f'"input": {{"command": "echo left {_SEP_CHAR} right"}}}}]}}}}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.tool_name != f"Read{_SEP}Bash"
    assert line.tool_name == f"Read{_SEP}Read | Bash"
    assert line.content_preview is not None
    assert line.content_preview.split(_SEP) == ["/a.py", "echo left | right"]
    assert len(line.content_preview.split(_SEP)) == 2


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


async def test_endpoint_response_keeps_the_two_tool_columns_aligned(
    mock_conversation_store,
):
    """The aligned columns must survive the HTTP endpoint's own serialization.

    Every other test in this file stops at ``get_conversation_log``, which
    returns ``ConversationLine``. The endpoint does NOT return those objects -
    it hand-copies each field into a separate ``ConversationLineResponse``,
    and that model is what FastAPI serializes and what the dashboard and CLI
    actually read. A field correct on ``ConversationLine`` and dropped or
    swapped at that hop would pass all of them.

    So this asserts on the endpoint's output. The fixture is the mixed-kind
    line: ``tool_name`` comes back as ``"Bash | "`` - a trailing EMPTY segment
    holding the ``tool_result``'s nameless slot. That exact value cannot arise
    from the two-list shape, which rendered a bare ``"Bash"`` with no slot for
    the second block and left the two columns different lengths.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        '{"type": "tool_use", "id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT", "name": "Bash", '
        '"input": {"command": "pytest --version"}}, '
        '{"type": "tool_result", "tool_use_id": "toolu_01Duj8L9PUh7xbAk8iBTQuJT", '
        '"content": "pytest 8.3.4"}]}, '
        '"uuid": "00000000-0000-0000-0000-000000000008"}',
    ]

    mgr = AsyncMock()
    mgr.store = AsyncMock()

    with (
        _patch_store(mock_conversation_store),
        patch("syn_api._wiring.get_projection_mgr", return_value=mgr),
        patch(
            "syn_api.prefix_resolver.resolve_or_raise",
            new=AsyncMock(return_value="claude-1"),
        ),
    ):
        from syn_api.routes.conversations import get_conversation_log_endpoint

        response = await get_conversation_log_endpoint("claude-1")

    line = response.lines[0]
    names = line.tool_name.split(_SEP)
    previews = line.content_preview.split(_SEP)
    assert len(names) == len(previews) == 2, (
        f"the endpoint lost a slot: {line.tool_name!r} / {line.content_preview!r}"
    )
    assert names == ["Bash", ""]
    assert previews == ["pytest --version", "pytest 8.3.4"]

    # Serialize the way FastAPI does. A field the response model declares but
    # never emits would still be readable as an attribute above.
    dumped = response.model_dump()["lines"][0]
    assert dumped["tool_name"] == f"Bash{_SEP}"
    assert dumped["content_preview"] == f"pytest --version{_SEP}pytest 8.3.4"


async def test_endpoint_response_survives_a_real_recorded_piped_command(
    mock_conversation_store,
):
    """A real, checked-in recording whose command contains a pipe, on the wire.

    ``v2.1.29_claude-sonnet-4-5_context-tracking.jsonl`` line 13 of the file
    (line 12 of the transcript, once the recorder's envelope is dropped) runs
    ``find /workspace -type f -name "*.py" | head -30`` - ONE tool block, and
    with the ASCII pipe as the separator it rendered TWO preview segments
    against one name, so the file's own invariant helper failed on it. That
    made the two-column contract false on data already committed to this
    repository, not on a constructed edge case; the recording was simply never
    fed to this endpoint by any test.

    Asserted through ``get_conversation_log_endpoint`` and ``model_dump`` - the
    response model the CLI and dashboard actually read - because that is where
    the review asked for it, and because the endpoint hand-copies each field
    into a separate model, a hop that every extractor-level test misses.
    """
    import pathlib

    fixture_path = (
        pathlib.Path(__file__).parents[3]
        / "lib"
        / "agentic-primitives"
        / "providers"
        / "workspaces"
        / "claude-cli"
        / "fixtures"
        / "recordings"
        / "v2.1.29_claude-sonnet-4-5_context-tracking.jsonl"
    )
    raw_lines = [
        line
        for line in fixture_path.read_text().splitlines()
        if line.strip() and not line.startswith('{"_recording"')
    ]
    mock_conversation_store.retrieve_session.return_value = raw_lines

    mgr = AsyncMock()
    mgr.store = AsyncMock()

    with (
        _patch_store(mock_conversation_store),
        patch("syn_api._wiring.get_projection_mgr", return_value=mgr),
        patch(
            "syn_api.prefix_resolver.resolve_or_raise",
            new=AsyncMock(return_value="claude-1"),
        ),
    ):
        from syn_api.routes.conversations import get_conversation_log_endpoint

        response = await get_conversation_log_endpoint("claude-1")

    # Serialize the way FastAPI does, then hold the invariant against the
    # DECODED wire values rather than against the in-process objects.
    dumped = response.model_dump()["lines"]
    assert len(dumped) == len(raw_lines)

    piped = [
        line
        for line in dumped
        if line["content_preview"] and _PIPE_IN_CONTENT in line["content_preview"]
    ]
    assert piped, (
        "this recording is the fixture because it contains piped commands; "
        "if it no longer does, this test is guarding nothing"
    )
    for line in piped:
        names = line["tool_name"].split(_SEP)
        previews = line["content_preview"].split(_SEP)
        assert len(names) == len(previews) == 1, (
            f"line {line['line_number']} has one tool block but renders "
            f"{len(names)} name and {len(previews)} preview segment(s): "
            f"{line['tool_name']!r} / {line['content_preview']!r}"
        )
        assert names == ["Bash"]

    # The pipeline itself, unmangled, straight off the wire.
    assert any(
        line["content_preview"] == 'find /workspace -type f -name "*.py" | head -30'
        for line in piped
    ), f"the recorded command did not survive verbatim: {[p['content_preview'] for p in piped]}"

    _assert_every_tool_block_is_represented(response.lines)


# One case per BRANCH of the line dispatcher, each carrying the separator
# character in a value that branch is the one to produce. The contract is not
# "the claude join escapes its input", it is "these two response fields never
# carry a forged boundary", and that is a claim about every branch. Three
# reviews of #1072 each found a different branch violating it, so this sweep
# is deliberately organised by branch rather than by symptom: an extractor with
# no case here is an extractor nothing is checking.
#
# Each case pins the EXACT wire value of both fields, not just their segment
# counts. A count-only assertion passes on a line that renders one segment of
# the wrong text, and the desync these guard is precisely wrong text in a
# real-looking slot.
_SEPARATOR_CASES = (
    (
        # codex command_execution, separator in the command's OUTPUT
        "codex_command_output",
        '{"type": "item.completed", "item": {"type": "command_execution", '
        f'"command": "grep -c x f", "aggregated_output": "alpha {_SEP_CHAR} beta"}}}}',
        "Bash",
        "alpha | beta",
    ),
    (
        # codex command_execution with no output falls back to the INVOCATION,
        # a second value this branch can put in the column
        "codex_command_invocation",
        '{"type": "item.completed", "item": {"type": "command_execution", '
        f'"command": "printf a {_SEP_CHAR} b", "aggregated_output": ""}}}}',
        "Bash",
        "printf a | b",
    ),
    (
        # codex file_change, separator in a changed PATH (legal in a filename)
        "codex_file_change_path",
        '{"type": "item.completed", "item": {"type": "file_change", '
        f'"changes": [{{"path": "/w/od{_SEP_CHAR}d.py"}}]}}}}',
        "Edit",
        "/w/od|d.py",
    ),
    (
        # codex item.started renders a bare system row - no entry, both None
        "codex_item_started",
        '{"type": "item.started", "item": {"type": "command_execution", '
        f'"command": "echo a {_SEP_CHAR} b"}}}}',
        None,
        None,
    ),
    (
        # codex agent_message: a preview with no tool name at all
        "codex_agent_message",
        '{"type": "item.completed", "item": {"type": "agent_message", '
        f'"text": "see {_SEP_CHAR} this"}}}}',
        None,
        "see | this",
    ),
    (
        "codex_turn_failed",
        f'{{"type": "turn.failed", "error": "boom {_SEP_CHAR} bang"}}',
        None,
        "boom | bang",
    ),
    (
        "codex_turn_completed",
        '{"type": "turn.completed", "usage": {"input_tokens": 1}}',
        None,
        None,
    ),
    (
        "codex_thread_started",
        '{"type": "thread.started", "thread_id": "t_1"}',
        None,
        None,
    ),
    (
        "codex_turn_started",
        '{"type": "turn.started"}',
        None,
        None,
    ),
    (
        "codex_error",
        '{"type": "error", "message": "x"}',
        None,
        None,
    ),
    (
        # claude, separator in an MCP-chosen tool NAME and in a preview
        "claude_tool_use",
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        f'{{"type": "tool_use", "id": "toolu_01aaaaaaaaaaaaaaaaaaaaaa", '
        f'"name": "mcp__od{_SEP_CHAR}d__run", '
        f'"input": {{"command": "echo a {_SEP_CHAR} b"}}}}]}}}}',
        "mcp__od|d__run",
        "echo a | b",
    ),
    (
        # claude tool_result: preview only, no name on the line at all
        "claude_tool_result",
        '{"type": "user", "message": {"role": "user", "content": ['
        '{"type": "tool_result", "tool_use_id": "toolu_01aaaaaaaaaaaaaaaaaaaaaa", '
        f'"content": "out {_SEP_CHAR} put"}}]}}}}',
        None,
        "out | put",
    ),
    (
        # generic fallback, separator in the tool NAME - the shape that made a
        # one-tool line render two name segments against one preview segment
        "generic_fallback_name",
        f'{{"type": "custom_event", "tool_name": "Read {_SEP_CHAR} Bash", "text": "one call"}}',
        "Read | Bash",
        "one call",
    ),
    (
        # generic fallback, separator in the CONTENT side
        "generic_fallback_content",
        f'{{"type": "custom_event", "tool_name": "Grep", "text": "hit {_SEP_CHAR} miss"}}',
        "Grep",
        "hit | miss",
    ),
    (
        # non-JSON line (a codex CLI diagnostic on stdout)
        "non_json_log_line",
        f"ERROR agent {_SEP_CHAR} crashed",
        None,
        "ERROR agent | crashed",
    ),
    (
        # valid JSON that is not an object - also routed to the log preview,
        # which renders the raw source text, quotes and all
        "json_scalar_log_line",
        f'"diag {_SEP_CHAR} nostic"',
        None,
        '"diag | nostic"',
    ),
)


@pytest.mark.parametrize(
    ("case_id", "raw", "expected_tool_name", "expected_preview"),
    [pytest.param(*case, id=case[0]) for case in _SEPARATOR_CASES],
)
async def test_no_extractor_branch_can_forge_a_column_boundary(
    mock_conversation_store,
    case_id,
    raw,
    expected_tool_name,
    expected_preview,
):
    """Every branch that writes these fields obeys the separator contract.

    Read through the ENDPOINT and its ``model_dump()``, not through
    ``get_conversation_log``: the endpoint hand-copies each field into a
    separate response model, and that copy is what the dashboard and CLI
    actually read.

    Before the fix only the claude branch rewrote the separator out of its
    values, so ``codex_command_output``, ``codex_command_invocation``,
    ``codex_file_change_path``, ``codex_agent_message``, ``codex_turn_failed``,
    ``generic_fallback_name``, ``generic_fallback_content``,
    ``non_json_log_line`` and ``json_scalar_log_line`` each produced a field
    whose split yielded a segment count the other field did not match (1-vs-2
    and 2-vs-1, or N-vs-None). They now assert the exact expected value, so a
    fix that only equalises the counts while mangling the text does not pass.

    The five cases expecting ``(None, None)`` are here for the opposite
    reason: those branches contribute no entry at all, and must keep
    contributing none - rendering an empty segment instead would be just as
    wrong, and silently so. ``codex_item_started`` is the one of them that
    carries the separator, because it is the one whose raw line has a value
    that would reach a column if the branch ever started emitting one.
    """
    mock_conversation_store.retrieve_session.return_value = [raw]

    mgr = AsyncMock()
    mgr.store = AsyncMock()

    with (
        _patch_store(mock_conversation_store),
        patch("syn_api._wiring.get_projection_mgr", return_value=mgr),
        patch(
            "syn_api.prefix_resolver.resolve_or_raise",
            new=AsyncMock(return_value="sess-1"),
        ),
    ):
        from syn_api.routes.conversations import get_conversation_log_endpoint

        response = await get_conversation_log_endpoint("sess-1")

    line = response.model_dump()["lines"][0]
    tool_name, preview = line["tool_name"], line["content_preview"]

    assert tool_name == expected_tool_name, (
        f"{case_id}: tool_name on the wire was {tool_name!r}, expected {expected_tool_name!r}"
    )
    assert preview == expected_preview, (
        f"{case_id}: content_preview on the wire was {preview!r}, expected {expected_preview!r}"
    )

    # The contract itself, restated as the property rather than as values: a
    # column that exists splits into the same number of segments as the other
    # column that exists, so an index into one is an index into the other.
    if tool_name is not None and preview is not None:
        assert len(tool_name.split(_SEP)) == len(preview.split(_SEP)), (
            f"{case_id}: columns desynchronized: {tool_name!r} / {preview!r}"
        )


def test_the_separator_sweep_covers_every_codex_line_type():
    """A new codex line shape must arrive with a separator case of its own.

    The defect this file now guards was never one bad function - it was a
    contract enforced in one branch while other branches wrote the same two
    fields. That recurs the moment a branch exists with nothing exercising it,
    so the sweep's coverage is asserted from the codex vocabulary itself
    rather than trusted to whoever adds the next item type.

    Claude's shapes and the generic fallback have no such enum to enumerate
    from; ``claude_tool_use``, ``claude_tool_result``, ``generic_fallback_*``
    and ``non_json_log_line`` cover those branches by hand.
    """
    from syn_shared.codex_stream import CodexItemType, CodexStreamType

    covered = "\n".join(raw for _, raw, _, _ in _SEPARATOR_CASES)
    missing = [t.value for t in (*CodexStreamType, *CodexItemType) if f'"{t.value}"' not in covered]
    assert not missing, (
        f"codex line types with no case in _SEPARATOR_CASES: {missing}. "
        "Add one carrying the separator character in a value that branch produces."
    )


async def test_a_non_string_tool_name_costs_one_column_not_the_whole_transcript(
    mock_conversation_store,
):
    """A column value that is not a string is no column value, and no fault.

    The generic fallback reads ``tool_name`` straight out of arbitrary JSON,
    so its type is whatever the producer wrote. Handing a non-string to
    ``ConversationLine`` raised ``ValidationError``, and
    ``get_conversation_log``'s enclosing ``except Exception`` turned that into
    ``QUERY_FAILED`` for the ENTIRE transcript - one malformed line took every
    good line with it.

    Column entries are typed ``str``, so a non-string cannot become one: the
    line renders with no tool name, keeps its preview, and its NEIGHBOURS are
    still returned. The second line here is the point of the fixture - assert
    only on the odd line and a fix that drops it silently would pass.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "custom_event", "tool_name": 123, "text": "still readable"}',
        '{"type": "custom_event", "tool_name": "Read", "text": "the next line"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("sess-1")

    assert isinstance(result, Ok), (
        "one line with a non-string tool_name failed the whole transcript request"
    )
    odd, neighbour = result.value.lines
    assert (odd.tool_name, odd.content_preview) == (None, "still readable")
    assert (neighbour.tool_name, neighbour.content_preview) == ("Read", "the next line")


async def test_a_tool_use_with_no_usable_name_still_renders_as_a_tool_row(
    mock_conversation_store,
):
    """The row's KIND is read from the raw blocks, not from what they rendered.

    A ``tool_use`` block whose ``name`` is missing or non-string contributes
    an empty name segment, so a line of only such blocks renders
    ``tool_name`` as None. Deriving the event type from the rendered columns
    would then call that line ``assistant`` and the reader would lose the one
    remaining signal that a tool ran at all - the preview would sit in a row
    that claims to be prose.

    Hence ``_is_claude_tool_use`` reads ``message.content[]`` directly. This
    test exists so that indirection is not tidied away as redundant.
    """
    mock_conversation_store.retrieve_session.return_value = [
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        '{"type": "tool_use", "id": "toolu_01bbbbbbbbbbbbbbbbbbbbbb", '
        '"input": {"command": "ls -la"}}]}, '
        '"uuid": "00000000-0000-0000-0000-000000000099"}',
    ]

    with _patch_store(mock_conversation_store):
        from syn_api.routes.conversations import get_conversation_log

        result = await get_conversation_log("claude-1")

    assert isinstance(result, Ok)
    line = result.value.lines[0]
    assert line.event_type == "tool_use", (
        f"a nameless tool_use line rendered as {line.event_type!r}, hiding that a tool ran"
    )
    assert line.tool_name is None
    assert line.content_preview == "ls -la"
