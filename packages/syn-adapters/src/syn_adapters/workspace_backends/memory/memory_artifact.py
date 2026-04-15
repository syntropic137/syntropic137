"""In-memory artifact collection adapter for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        Artifact,
        ArtifactCollectionResult,
        IsolationHandle,
    )


class MemoryArtifactAdapter(InMemoryAdapter):
    """In-memory implementation of ArtifactCollectionPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates artifact collection without filesystem access.
    Inherits environment guard from InMemoryAdapter.
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        super().__init__()
        self._artifacts: dict[str, list[Artifact]] = {}  # isolation_id -> artifacts

    async def collect(
        self,
        handle: IsolationHandle,
        _patterns: list[str],
        *,
        _destination: str | None = None,
    ) -> ArtifactCollectionResult:
        """Simulate artifact collection.

        Args:
            handle: Isolation handle
            patterns: Glob patterns (ignored in mock)
            destination: Destination path (ignored in mock)

        Returns:
            ArtifactCollectionResult with pre-configured artifacts
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            ArtifactCollectionResult,
        )

        artifacts = self._artifacts.get(handle.isolation_id, [])

        return ArtifactCollectionResult(
            success=True,
            artifacts=tuple(artifacts),
            total_size_bytes=sum(a.size_bytes for a in artifacts),
        )

    async def list_artifacts(
        self,
        handle: IsolationHandle,
        _path: str = "/workspace",
    ) -> list[Artifact]:
        """List mock artifacts.

        Args:
            handle: Isolation handle
            path: Directory path (ignored in mock)

        Returns:
            Pre-configured artifact list
        """
        return self._artifacts.get(handle.isolation_id, [])

    def add_artifact(self, handle: IsolationHandle, artifact: Artifact) -> None:
        """Add artifact for testing.

        Args:
            handle: Isolation handle
            artifact: Artifact to add
        """
        if handle.isolation_id not in self._artifacts:
            self._artifacts[handle.isolation_id] = []
        self._artifacts[handle.isolation_id].append(artifact)
