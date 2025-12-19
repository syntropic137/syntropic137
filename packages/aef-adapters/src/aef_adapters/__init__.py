"""External integrations for Agentic Engineering Framework.

This package provides adapters for:
- AI Agents (Claude, OpenAI) - see `aef_adapters.agents`
- Storage (PostgreSQL, In-Memory) - see `aef_adapters.storage`
- Object Storage (Local, MinIO, Supabase) - see `aef_adapters.object_storage`
- Events (Event storage and buffering) - see `aef_adapters.events`
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
from aef_adapters.events import AgentEventStore, EventBuffer
from aef_adapters.object_storage import (
    LocalStorage,
    MinioStorage,
    StorageProtocol,
    SupabaseStorage,
    get_storage,
)

__all__ = [
    "AgentConfig",
    "AgentError",
    "AgentEventStore",
    "AgentMessage",
    "AgentProtocol",
    "AgentProvider",
    "AgentResponse",
    "EventBuffer",
    "LocalStorage",
    "MinioStorage",
    "StorageProtocol",
    "SupabaseStorage",
    "__version__",
    "get_agent",
    "get_available_agents",
    "get_storage",
]
