"""Claude agent helper functions.

Extracted from claude.py to reduce module complexity.
"""

from __future__ import annotations

from syn_adapters.agents.protocol import AgentMessage, AgentRole


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
