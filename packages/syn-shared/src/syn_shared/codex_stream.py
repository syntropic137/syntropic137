"""Shared, type-safe identifiers for the ``codex exec --json`` stream shape.

The codex CLI emits a JSONL event stream whose top-level ``type`` is one of a
small closed set (``thread.started`` / ``turn.started`` / ``item.started`` /
``item.completed`` / ``turn.completed`` / ``turn.failed``), and whose ``item``
payloads carry their own ``item.type`` (``agent_message`` / ``command_execution``
/ ``file_change``).

These StrEnums replace bare string literals so every reader of a codex stream
(the live ``CodexStreamProcessor`` and the after-the-fact conversation-log
renderer) compares against ONE source of truth. ``StrEnum`` members compare
equal to their string value, so a raw ``data.get("type")`` (a plain ``str``)
can still be compared against a member without changing the field type.
"""

from __future__ import annotations

from enum import StrEnum


class CodexStreamType(StrEnum):
    """A codex stream event's top-level ``type`` value."""

    THREAD_STARTED = "thread.started"
    TURN_STARTED = "turn.started"
    ITEM_STARTED = "item.started"
    ITEM_COMPLETED = "item.completed"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"


class CodexItemType(StrEnum):
    """A codex ``item`` payload's ``type`` value."""

    AGENT_MESSAGE = "agent_message"
    """Conversational text the model produced (the "talking")."""

    COMMAND_EXECUTION = "command_execution"
    """A shell command the model ran."""

    FILE_CHANGE = "file_change"
    """One or more file edits the model made."""


# Tool-name labels a codex item maps onto in the observability timeline.
# Mirrors CodexStreamProcessor so the transcript and the timeline agree.
CODEX_TOOL_NAME_COMMAND = "Bash"
CODEX_TOOL_NAME_FILE_CHANGE = "Edit"
