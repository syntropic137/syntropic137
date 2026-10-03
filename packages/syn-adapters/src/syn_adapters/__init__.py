"""External integrations for Syntropic137.

This package provides adapters for:
- Storage (PostgreSQL, In-Memory) - see `syn_adapters.storage`
- Object Storage (Local, MinIO) - see `syn_adapters.object_storage`
- Events (Event storage and buffering) - see `syn_adapters.events`
"""

#: NO ``__version__`` HERE. This package had one, hardcoded "0.1.0", while its
#: pyproject.toml said 0.29.0 - a second home for the release number that
#: `just bump-version` does not write and therefore could only ever be wrong.
#: That is the drift #1380 is about; the packages that must REPORT a running
#: build (syn-api, syn-collector) read it from importlib.metadata through one
#: accessor, and a library that reports nothing does not need a copy at all.

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
    "get_storage",
]
