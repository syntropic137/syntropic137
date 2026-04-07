"""External integrations for Syntropic137.

This package provides adapters for:
- Storage (PostgreSQL, In-Memory) - see `syn_adapters.storage`
- Object Storage (Local, MinIO) - see `syn_adapters.object_storage`
- Events (Event storage and buffering) - see `syn_adapters.events`
"""

__version__ = "0.1.0"

# Re-export commonly used items for convenience
from syn_adapters.events import AgentEventStore, EventBuffer
from syn_adapters.object_storage import (
    LocalStorage,
    MinioStorage,
    StorageProtocol,
    get_storage,
)

__all__ = [
    "AgentEventStore",
    "EventBuffer",
    "LocalStorage",
    "MinioStorage",
    "StorageProtocol",
    "__version__",
    "get_storage",
]
