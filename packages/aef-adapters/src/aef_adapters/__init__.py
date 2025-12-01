"""External integrations for Agentic Engineering Framework.

This package provides adapters for:
- AI Agents (Claude, OpenAI) - see `aef_adapters.agents`
- Storage (PostgreSQL, In-Memory) - see `aef_adapters.storage`
"""

__version__ = "0.1.0"

# Re-export commonly used items for convenience
from aef_adapters.agents import (
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentProtocol,
    AgentProvider,
    AgentResponse,
    get_agent,
    get_available_agents,
)

__all__ = [
    "AgentConfig",
    "AgentError",
    "AgentMessage",
    "AgentProtocol",
    "AgentProvider",
    "AgentResponse",
    "__version__",
    "get_agent",
    "get_available_agents",
]
