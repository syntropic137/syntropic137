"""Reads stored conversation-log lines as Claude Code and Codex wrote them (#1424).

The adapter behind ``ConversationLogReader``. A conversation log is the agent's
raw stdout, one line per entry: Claude Code ``stream-json`` events, Codex
``--json`` events, and the plain-text diagnostics and banners Codex prints
beside them. How each of those spells a tool call, a tool result or a message
is harness knowledge, which changes when a CLI ships, so it lives here rather
than in the API route. What a line MEANS - ``ConversationLogRow`` - is owned by
``syn_domain.contexts.agent_sessions``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from syn_domain.contexts.agent_sessions import (
    ConversationLogRow,
    NonStringEventTypeError,
    UnreadableConversationLine,
)
from syn_shared.codex_stream import (
    CODEX_TOOL_NAME_COMMAND,
    CODEX_TOOL_NAME_FILE_CHANGE,
    CodexItemType,
    CodexStreamType,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: What ``json.loads`` can return. Every record below is read as one of these,
#: never as ``Any``, so a field is narrowed before it is used.
#:
#: Three reads below ``cast`` instead of narrowing: a non-string ``text``,
#: ``result.output`` or ``type``. Each passed through unchecked before #1424
#: moved this parser out of the route, and #1424 is behaviour-neutral, so they
#: still do; ``ConversationLine`` in the API is what rejects one.
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


def _get_top_level_content(data: Mapping[str, JsonValue]) -> str:
    """Check top-level ``content`` / ``text`` fields."""
    content = data.get("content") or data.get("text") or ""
    if content and isinstance(content, str):
        return content
    return ""


def _get_message_content(data: Mapping[str, JsonValue]) -> str:
    """Check nested ``message.content`` (Claude Code JSONL format)."""
    msg = data.get("message")
    if not isinstance(msg, dict):
        return ""
    msg_content = msg.get("content")
    if isinstance(msg_content, str):
        return msg_content
    if isinstance(msg_content, list):
        return next(
            (cast("str", p["text"]) for p in msg_content if isinstance(p, dict) and p.get("text")),
            "",
        )
    return ""


def _get_result_content(data: Mapping[str, JsonValue]) -> str:
    """Check nested ``result.output`` / ``result.text``."""
    result = data.get("result")
    if isinstance(result, dict):
        return cast("str", result.get("output", "") or result.get("text", ""))
    return ""


def _extract_content_preview(data: Mapping[str, JsonValue]) -> str:
    """Extract content text from a parsed JSONL object.

    Checks top-level fields, then nested message.content (Claude Code format),
    then result.output.
    """
    return _get_top_level_content(data) or _get_message_content(data) or _get_result_content(data)


class TranscriptEventType(StrEnum):
    """Normalized display event-type a transcript line renders as.

    Claude's ``stream-json`` already emits ``assistant`` / ``user`` / ``result``
    / ``system`` as its top-level ``type``; the codex path is normalized ONTO
    the same vocabulary so the dashboard's single color map styles both. These
    strings are mirrored by ``conversationEventColors`` in the frontend
    (``sessionConstants.ts``) - keep them in sync.
    """

    ASSISTANT = "assistant"
    TOOL_USE = "tool_use"
    SYSTEM = "system"
    RESULT = "result"
    ERROR = "error"
    LOG = "log"
    """A non-JSON CLI diagnostic line (codex writes these to stdout)."""


_PREVIEW_LEN = 200

# Codex writes plain-text banners to stdout alongside its JSONL events. These
# are pure CLI chrome (not conversation, not diagnostics) and are dropped from
# the transcript entirely. Matched by prefix on non-JSON lines only.
# Source: CodexStreamProcessor golden-fixture note (2026-07-23).
_CODEX_CLI_NOISE_PREFIXES = (
    "Reading additional input from stdin",
    "warning: --full-auto is deprecated",
)

_CODEX_STREAM_TYPES = frozenset(t.value for t in CodexStreamType)


def _log_line_preview(raw: str) -> str | None:
    """Preview for a non-object transcript line (CLI diagnostic or JSON scalar)."""
    stripped = raw.strip() if raw else ""
    return stripped[:_PREVIEW_LEN] if stripped else None


def _is_codex_cli_noise(raw: str) -> bool:
    """True for a codex plain-text banner line that should not appear at all."""
    stripped = raw.strip()
    if not stripped or stripped.startswith("{"):
        return False
    return any(stripped.startswith(prefix) for prefix in _CODEX_CLI_NOISE_PREFIXES)


def _codex_file_change_preview(item: Mapping[str, JsonValue]) -> str | None:
    """Join the changed paths in a codex ``file_change`` item into a preview."""
    changes = item.get("changes")
    if not isinstance(changes, list):
        return None
    paths = [str(c.get("path", "")) for c in changes if isinstance(c, dict) and c.get("path")]
    joined = ", ".join(paths)
    return joined[:_PREVIEW_LEN] if joined else None


def _codex_command_execution_preview(item: Mapping[str, JsonValue]) -> str | None:
    """Preview for a completed codex ``command_execution`` item.

    Prefers the result (``aggregated_output``); falls back to the invocation
    (``command``) when the output is empty (e.g. a command that produced no
    stdout), so the row is never blank.
    """
    output = item.get("aggregated_output")
    if isinstance(output, str) and output:
        return output[:_PREVIEW_LEN]
    command = item.get("command")
    return command[:_PREVIEW_LEN] if isinstance(command, str) and command else None


# Claude Code's stream-json nests a tool call inside
# ``message.content[].{type: "tool_use", name, input}`` (assistant lines) and
# the matching result inside
# ``message.content[].{type: "tool_result", content, is_error}`` (user
# lines). There is no top-level ``tool_name``/``name`` key for either, so the
# generic extractor below always falls through to None for these - this is
# the claude-side counterpart to ``_extract_codex_fields``.
_TOOL_PREVIEW_LEN = 100

# Priority order of input keys to surface as a tool_use preview, checked by
# field name rather than dispatching on tool name so new/renamed tools still
# get a preview: ``command`` for Bash, ``file_path`` for Read/Edit/Write,
# ``pattern`` for Grep/Glob, etc.
_CLAUDE_TOOL_INPUT_KEYS = (
    "command",
    "file_path",
    "pattern",
    "path",
    "notebook_path",
    "url",
    "query",
    "description",
    "prompt",
)


def _claude_tool_use_preview(input_data: Mapping[str, JsonValue]) -> str | None:
    """Pick the first populated salient field from a ``tool_use`` block's input."""
    for key in _CLAUDE_TOOL_INPUT_KEYS:
        value = input_data.get(key)
        if isinstance(value, str) and value:
            return value[:_TOOL_PREVIEW_LEN]
    return None


def _claude_tool_result_text(content: object) -> str:
    """Flatten a ``tool_result`` block's ``content`` into plain text.

    ``content`` is either a bare string, or a list of ``{"type": "text",
    "text": ...}`` blocks (seen in real recordings, e.g. subagent tool
    results) - join those in order.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part["text"]
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _claude_tool_result_preview(item: Mapping[str, JsonValue]) -> str | None:
    """Preview for a ``tool_result`` block: its first output line, error-flagged."""
    text = _claude_tool_result_text(item.get("content"))
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    if item.get("is_error") is True:
        return f"[error] {first_line}"[:_TOOL_PREVIEW_LEN] if first_line else "[error]"
    return first_line[:_TOOL_PREVIEW_LEN] if first_line else None


# One raw line maps to N tool blocks - ``message.content[]`` is a LIST, and
# every tool block in it is a distinct call or result - but to only ONE
# ``ConversationLogRow``, whose ``tool_name``/``content_preview`` are each a
# single ``str | None``. So the blocks are joined into two columns rather than
# dropped.
#
# The contract on the joined values, which consumers may rely on: splitting
# either field on this separator yields ONE segment per entry the line
# contributed, in order, and the two fields split to the same length. A
# segment is empty where that entry has no value for that column. So segment i
# of ``tool_name`` and segment i of ``content_preview`` always describe the
# same entry. Either field is None when NO entry on the line contributed to it.
#
# That contract holds for EVERY input, not just for inputs that happen not to
# collide, and it holds because of WHERE it is enforced rather than because
# every extractor remembers to honour it. No extractor produces these two
# strings at all: each returns a list of ``_ColumnEntry``, and
# ``_render_tool_columns`` turns that list into the pair through
# ``_join_column``, the only function in this module that names the separator
# at all - grep it and the whole rule is on screen. An entry's own text can no
# more forge a segment boundary than omit one, because the rewrite happens
# there, below every branch, on the way out.
#
# That placement is the fix for a defect found three separate times in three
# reviews of #1072. The rule used to live inside the claude branch's own join,
# so it covered the claude branch and nothing else: a broken bar occurring in
# codex command output, in a changed file path, in a codex agent message, in a
# CLI diagnostic line or in a generic-fallback tool name still forged a
# boundary and desynchronized the two columns. Each of those is a separate
# writer of the same two fields, and patching them one at a time would have
# left the next writer free to break it again. Enforcing it at the single
# point where the fields are SET means a new extractor cannot violate the
# contract even if its author has never read this comment - the return type
# gives it no way to.
#
# WHICH character carries the structure is then purely a question of how often
# that rewrite has to fire on real content, and the answer is why this is a
# BROKEN BAR (U+00A6, "\u00a6") rather than the ASCII pipe it used to be
# (#1072 review). These values are shell commands and command output, where a
# real "|" is ordinary content: ``find /workspace -type f -name "*.py" | head
# -30`` is a checked-in recording line, and with the pipe as the separator that
# one real command manufactured a second apparent segment for a line with one
# tool block. Escaping the pipe instead would have mangled every command
# pipeline in the transcript to fix a collision that only matters when a line
# carries several blocks. A broken bar has never appeared in this content, so
# the rewrite is effectively never reached and a real pipe reaches the reader
# byte-for-byte - but correctness does not rest on that rarity, only fidelity
# does.
#
# ", " (the separator ``_codex_file_change_preview`` uses for paths) is unusable
# here for the same reason the pipe was: commas are ordinary content in a
# command, so escaping them would rewrite almost every preview.
_TOOL_FIELD_SEP_CHAR = "\u00a6"
_TOOL_FIELD_SEP = f" {_TOOL_FIELD_SEP_CHAR} "

# What a separator character occurring in an entry's own text is displayed as.
# The pipe is the closest reading of a broken bar, and is safe here precisely
# because the pipe no longer carries any structural meaning in these fields.
_TOOL_FIELD_SEP_CHAR_AS_CONTENT = "|"


@dataclass(frozen=True)
class _ColumnEntry:
    """One transcript entry, in the two columns it renders into.

    An entry is whatever occupies one slot of ``tool_name`` /
    ``content_preview``: a claude ``tool_use`` block (name and preview), a
    claude ``tool_result`` block (preview only), a codex tool item, or the
    plain text of a message, an error or a CLI diagnostic (preview only). Both
    fields are always ``str`` and never None - an entry missing one side
    carries the empty string instead of being skipped, which is what keeps one
    slot per entry in BOTH columns.

    That is the whole point of this type, and of every extractor returning a
    list of them instead of two strings. Segment *i* of ``tool_name`` then
    describes the same entry as segment *i* of ``content_preview`` by
    construction. The shape before it accumulated the two columns as two
    independently-filtered lists, so an entry contributing one side but not the
    other shifted every later entry of the shorter list up by one and the join
    made the shift invisible - the reader saw a real preview confidently
    attributed to the wrong tool (#1072 review).
    """

    name: str = ""
    preview: str = ""

    @classmethod
    def of(cls, name: object = None, preview: str | None = None) -> _ColumnEntry:
        """Build an entry from a raw name and an already-built preview.

        ``name`` is typed ``object`` because it is read straight out of
        arbitrary JSON - claude's block ``name``, or whatever the producer of
        a generic line wrote into ``tool_name`` - so its type is not ours to
        assume. A non-string is not a column value and becomes the empty
        segment, rather than reaching the response model and failing
        validation, which would fail the WHOLE transcript request rather than
        the one odd line.

        ``preview`` needs no such guard: every preview is built by one of the
        ``_*_preview`` helpers above, which all return ``str | None``.
        """
        return cls(
            name=name if isinstance(name, str) else "",
            preview=preview or "",
        )


def _join_column(values: list[str]) -> str | None:
    """Join one column's per-entry values into its ``str | None`` field.

    Empty values are KEPT as empty segments - that is what preserves one
    segment per entry, and therefore the positional correspondence between the
    two columns. A column no entry contributed anything to (``tool_name`` on a
    line of only ``tool_result`` blocks, or on any non-tool line) collapses to
    None rather than rendering as a row of bare separators.
    """
    if not any(values):
        return None
    return _TOOL_FIELD_SEP.join(
        value.replace(_TOOL_FIELD_SEP_CHAR, _TOOL_FIELD_SEP_CHAR_AS_CONTENT) for value in values
    )


def _render_tool_columns(entries: Sequence[_ColumnEntry]) -> tuple[str | None, str | None]:
    """Render a line's entries into its ``(tool_name, content_preview)`` pair.

    The single point at which these two response fields are set. Both columns
    come from the SAME list in the SAME order, so they cannot differ in
    length; and ``_join_column`` strips the separator character out of every
    value on the way through, so no value can forge a boundary. Those two
    properties together ARE the contract stated above - stated once, checkable
    in one place, and unavailable to any extractor to get wrong.

    Escaping inside the producers instead would take one copy of the rule per
    producer and still not hold, because each truncates AFTER building its text
    and a truncation can land anywhere.
    """
    return (
        _join_column([entry.name for entry in entries]),
        _join_column([entry.preview for entry in entries]),
    )


_CLAUDE_TOOL_USE = "tool_use"
_CLAUDE_TOOL_RESULT = "tool_result"


def _is_claude_tool_use(item: object) -> bool:
    """True for a ``message.content[]`` block that is a tool CALL."""
    return isinstance(item, dict) and item.get("type") == _CLAUDE_TOOL_USE


def _claude_tool_block(item: Mapping[str, JsonValue]) -> _ColumnEntry | None:
    """Normalize ONE ``message.content[]`` block, or None if it is not a tool block.

    None covers plain ``text``, ``thinking`` and unrecognized types, which the
    caller skips - they occupy no slot in either column.
    """
    item_type = item.get("type")
    if item_type == _CLAUDE_TOOL_USE:
        input_data = item.get("input")
        preview = _claude_tool_use_preview(input_data) if isinstance(input_data, dict) else None
        return _ColumnEntry.of(name=item.get("name"), preview=preview)
    if item_type == _CLAUDE_TOOL_RESULT:
        return _ColumnEntry.of(preview=_claude_tool_result_preview(item))
    return None


def _collect_claude_tool_blocks(content: list[JsonValue]) -> list[_ColumnEntry]:
    """Every tool block in one message's ``content``, in order; empty if there are none."""
    blocks: list[_ColumnEntry] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        block = _claude_tool_block(item)
        if block is not None:
            blocks.append(block)
    return blocks


def _extract_claude_tool_fields(
    data: Mapping[str, JsonValue],
) -> tuple[str, list[_ColumnEntry]] | None:
    """Normalize a claude ``tool_use``/``tool_result`` line, or None otherwise.

    Only ``assistant`` and ``user`` lines whose ``message.content[]`` contains
    a ``tool_use`` or ``tool_result`` block are handled here; every other
    shape (plain assistant text, a plain user turn, system/init, result,
    an unrecognized type) returns None so the caller falls back to the
    generic extractor, which already handles those correctly.

    EVERY tool block on the line is represented, not just the first. An
    assistant message that makes parallel tool calls carries one ``tool_use``
    block per call, and the matching ``user`` message carries one
    ``tool_result`` block per call; ``agentic_isolation``'s claude_cli
    ``event_parser`` - the harness-side authority on this format - likewise
    emits one observability event per block rather than stopping at the first.
    Returning on the first block silently deleted the rest of the line (#1067
    review).

    Each block's preview is bounded by ``_TOOL_PREVIEW_LEN``, so the rendered
    value is bounded by the block count, which is bounded by the raw line -
    already returned in full and unbounded as the line's ``raw``.
    """
    top_type = data.get("type")
    if top_type not in ("assistant", "user"):
        return None
    message = data.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None

    blocks = _collect_claude_tool_blocks(content)
    if not blocks:
        return None

    # A line holding any tool_use renders as a tool row; a line holding only
    # tool_results keeps its own top-level type, as before this change. Read
    # from the raw content rather than the blocks, so a tool_use whose ``name``
    # is missing or non-string still renders as a tool row.
    event_type = (
        TranscriptEventType.TOOL_USE
        if any(_is_claude_tool_use(item) for item in content)
        else str(top_type)
    )
    return event_type, blocks


_CODEX_TOOL_ITEM_TYPES = frozenset((CodexItemType.COMMAND_EXECUTION, CodexItemType.FILE_CHANGE))


def _codex_item_fields(
    item: Mapping[str, JsonValue], stream_type: CodexStreamType
) -> tuple[str, list[_ColumnEntry]]:
    """Map a codex stream ``item`` to its (event_type, column entries).

    Codex emits both ``item.started`` and ``item.completed`` for the same
    tool call. Only ``item.completed`` renders a tool row - ``item.started``
    is normalized to a plain ``system`` line with no tool_name/preview, so
    the raw line still appears (expandable) but never duplicates the
    completed row, whether or not the completed side has output.
    """
    item_type = item.get("type")
    if item_type == CodexItemType.AGENT_MESSAGE:
        text = item.get("text")
        preview = text[:_PREVIEW_LEN] if isinstance(text, str) and text else None
        return TranscriptEventType.ASSISTANT, [_ColumnEntry.of(preview=preview)]
    if item_type in _CODEX_TOOL_ITEM_TYPES and stream_type == CodexStreamType.ITEM_STARTED:
        return TranscriptEventType.SYSTEM, []
    if item_type == CodexItemType.COMMAND_EXECUTION:
        return (
            TranscriptEventType.TOOL_USE,
            [
                _ColumnEntry.of(
                    name=CODEX_TOOL_NAME_COMMAND,
                    preview=_codex_command_execution_preview(item),
                )
            ],
        )
    if item_type == CodexItemType.FILE_CHANGE:
        return (
            TranscriptEventType.TOOL_USE,
            [
                _ColumnEntry.of(
                    name=CODEX_TOOL_NAME_FILE_CHANGE,
                    preview=_codex_file_change_preview(item),
                )
            ],
        )
    return TranscriptEventType.SYSTEM, []


def _extract_codex_fields(
    data: Mapping[str, JsonValue],
) -> tuple[str, list[_ColumnEntry]] | None:
    """Normalize a codex stream event, or None if the line is not codex-shaped.

    Codex's ``--json`` events use a closed set of top-level ``type`` values
    (``item.completed`` etc.) unrelated to claude's ``stream-json`` types, so a
    ``type`` in that set unambiguously identifies a codex line. Returning None
    lets the caller fall back to claude parsing.
    """
    raw_type = data.get("type")
    if raw_type not in _CODEX_STREAM_TYPES:
        return None
    if raw_type == CodexStreamType.TURN_COMPLETED:
        return TranscriptEventType.RESULT, []
    if raw_type == CodexStreamType.TURN_FAILED:
        error = data.get("error")
        preview = str(error)[:_PREVIEW_LEN] if error else None
        return TranscriptEventType.ERROR, [_ColumnEntry.of(preview=preview)]
    item = data.get("item")
    if not isinstance(item, dict):
        return TranscriptEventType.SYSTEM, []
    return _codex_item_fields(item, CodexStreamType(raw_type))


def _extract_line_fields(
    raw: str,
) -> tuple[str | None, list[_ColumnEntry]]:
    """Extract a line's event_type and its column entries from a JSONL line.

    Handles both claude ``stream-json`` and codex ``--json`` line shapes.
    Every branch returns entries rather than the two rendered strings, so the
    separator contract is settled once by ``_render_tool_columns`` for all of
    them - see the contract comment above.
    """
    try:
        data: JsonValue = json.loads(raw)
    except (json.JSONDecodeError, AttributeError):
        # Non-JSON line: a codex CLI diagnostic (e.g. an ERROR trace) on stdout.
        # Label it ``log`` rather than leaving it to render as "unknown".
        return TranscriptEventType.LOG, [_ColumnEntry.of(preview=_log_line_preview(raw))]

    # Valid JSON but not an object (a bare scalar/array). Both the codex and
    # claude extractors call ``.get()``, so guard here - otherwise one odd line
    # (``null``, ``[]``, ``"diagnostic"``) would raise and fail the WHOLE
    # transcript request with QUERY_FAILED.
    if not isinstance(data, dict):
        return TranscriptEventType.LOG, [_ColumnEntry.of(preview=_log_line_preview(raw))]

    codex = _extract_codex_fields(data)
    if codex is not None:
        return codex

    claude_tool = _extract_claude_tool_fields(data)
    if claude_tool is not None:
        return claude_tool

    event_type = data.get("type") or data.get("event_type")
    content = _extract_content_preview(data)
    entry = _ColumnEntry.of(
        name=data.get("tool_name") or data.get("name"),
        preview=content[:_PREVIEW_LEN] if content else None,
    )
    if event_type is not None and not isinstance(event_type, str):
        # Read straight out of the line, so not ours to trust: a row's event
        # type is a string or nothing, and ``read_row`` reports the line as
        # unreadable rather than handing on a row that breaks its own type.
        # Checked last, so a line the content read already fails on keeps
        # that failure as its cause.
        raise NonStringEventTypeError(event_type)
    return event_type, [entry]


class StoredConversationLogReader:
    """``ConversationLogReader`` for Claude Code and Codex conversation logs."""

    def belongs_in_log(self, raw: str) -> bool:
        """False only for a codex plain-text banner line."""
        return not _is_codex_cli_noise(raw)

    def read_row(self, raw: str) -> ConversationLogRow | UnreadableConversationLine:
        """The row one stored line renders as, or why it has none; never raises.

        The extractors read arbitrary JSON, so a field of the wrong shape can
        still fail inside them (an unhashable ``type``, a non-string text
        block, a decoder recursion limit, a non-string event type). That
        failure is returned as the line's cause rather than raised.
        """
        try:
            event_type, entries = _extract_line_fields(raw)
            tool_name, preview = _render_tool_columns(entries)
        except Exception as exc:  # the port contract: an odd line never raises
            return UnreadableConversationLine(cause=exc)
        return ConversationLogRow(
            event_type=event_type,
            tool_name=tool_name,
            content_preview=preview,
        )
