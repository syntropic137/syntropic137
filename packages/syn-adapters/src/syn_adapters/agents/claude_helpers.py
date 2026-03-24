"""Claude agent helper functions.

Extracted from claude.py to reduce module complexity.
complete_request has been moved to claude_complete.py.
stream_request has been moved to claude_stream.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.agents.claude_complete import complete_request
from syn_adapters.agents.claude_stream import stream_request
from syn_adapters.agents.protocol import (
    AgentMessage,
    AgentRole,
)
from syn_shared.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

__all__ = ["convert_messages", "resolve_model", "get_context_window", "complete_request", "stream_request"]


def convert_messages(
    messages: list[AgentMessage],
) -> tuple[str | None, list[dict[str, str]]]:
    """Convert AgentMessages to Anthropic format."""
    system_prompt: str | None = None
    converted: list[dict[str, str]] = []
    for msg in messages:
        if msg.role == AgentRole.SYSTEM:
            system_prompt = msg.content
        else:
            converted.append({"role": msg.role.value, "content": msg.content})
    return system_prompt, converted


def resolve_model(model: str) -> str:
    """Resolve model alias to specific API version."""
    from syn_adapters.agents.models import resolve_model as _resolve

    return _resolve(model)


def get_context_window(model: str) -> int:
    """Get context window size for a model."""
    from syn_adapters.agents.models import get_model_registry

    return get_model_registry().get_context_window(model)
