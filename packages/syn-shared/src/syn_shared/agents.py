"""Shared, type-safe identifiers for workflow phase agents.

These replace bare string literals ("claude" / "codex" / "claude-interactive")
that were previously compared in many places across the domain, adapter, and API
layers. `StrEnum` members compare equal to their string value, so a loose
``provider: str`` field can still be compared against a member
(``provider == AgentProvider.CODEX``) without changing the field type.
"""

from __future__ import annotations

from enum import StrEnum


class AgentProvider(StrEnum):
    """A workflow phase's ``agent_config.provider`` value.

    The domain ``provider`` field stays a plain ``str`` (it also accepts
    test-only values like ``"mock"``); these members are the KNOWN production
    providers to compare against, never a bare literal.
    """

    CLAUDE = "claude"
    """Default headless ``claude -p`` docker-exec path."""

    CLAUDE_INTERACTIVE = "claude-interactive"
    """Interactive-tmux pane path (parked hedge, syn137#777)."""

    CODEX = "codex"
    """Headless ``codex exec`` docker-exec path (the codex bridge)."""


class AgentRunner(StrEnum):
    """Which stream processor drives a headless phase (claude vs codex)."""

    CLAUDE = "claude"
    CODEX = "codex"
