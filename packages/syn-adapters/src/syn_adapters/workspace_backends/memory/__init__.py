"""In-memory workspace adapters for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

All adapters in this module will raise TestEnvironmentRequiredError
if used outside of APP_ENVIRONMENT=test or APP_ENVIRONMENT=testing.

This is enforced per ADR-004 and ADR-023.

Usage:
    # Set environment
    os.environ["APP_ENVIRONMENT"] = "test"

    # Then use adapters
    from syn_adapters.workspace_backends.memory import MemoryIsolationAdapter

    adapter = MemoryIsolationAdapter()
    handle = await adapter.create(config)
"""

from syn_adapters.workspace_backends.memory.memory_adapter import (
    MemoryIsolationAdapter,
    TestEnvironmentRequiredError,
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
