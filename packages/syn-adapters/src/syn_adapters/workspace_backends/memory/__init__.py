"""In-memory workspace adapters for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

All adapters inherit from InMemoryAdapter, which enforces
test/offline-only usage via settings.uses_in_memory_stores.

See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
"""

from syn_adapters.in_memory import InMemoryAdapterError as TestEnvironmentRequiredError
from syn_adapters.workspace_backends.memory.memory_adapter import (
    MemoryIsolationAdapter,
)
from syn_adapters.workspace_backends.memory.memory_artifact import (
    MemoryArtifactAdapter,
)
from syn_adapters.workspace_backends.memory.memory_sidecar import (
    MemorySidecarAdapter,
)
from syn_adapters.workspace_backends.memory.memory_stream import (
    MemoryEventStreamAdapter,
)
from syn_adapters.workspace_backends.memory.memory_token import (
    MemoryTokenInjectionAdapter,
)

__all__ = [
    "MemoryArtifactAdapter",
    "MemoryEventStreamAdapter",
    "MemoryIsolationAdapter",
    "MemorySidecarAdapter",
    "MemoryTokenInjectionAdapter",
    "TestEnvironmentRequiredError",
]
