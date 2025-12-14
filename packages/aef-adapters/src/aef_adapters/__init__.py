"""External integrations for Agentic Engineering Framework.

This package provides adapters for:
- AI Agents (Claude, OpenAI) - see `aef_adapters.agents`
- Storage (PostgreSQL, In-Memory) - see `aef_adapters.storage`
- Object Storage (Local, MinIO, Supabase) - see `aef_adapters.object_storage`
- Hooks (Observability) - see `aef_adapters.hooks`
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
from aef_adapters.hooks import (
    AEFHookClient,
    ValidationResult,
    ValidatorRegistry,
    get_hook_client,
)
from aef_adapters.object_storage import (
    LocalStorage,
    MinioStorage,
    StorageProtocol,
    SupabaseStorage,
    get_storage,
)

__all__ = [
    "AEFHookClient",
    "AgentConfig",
    "AgentError",
    "AgentMessage",
    "AgentProtocol",
    "AgentProvider",
    "AgentResponse",
    "LocalStorage",
    "MinioStorage",
    "StorageProtocol",
    "SupabaseStorage",
    "ValidationResult",
    "ValidatorRegistry",
    "__version__",
    "get_agent",
    "get_available_agents",
    "get_hook_client",
    "get_storage",
]
