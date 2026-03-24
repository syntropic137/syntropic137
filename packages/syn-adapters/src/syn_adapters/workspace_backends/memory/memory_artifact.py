"""In-memory artifact collection adapter for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

See ADR-004 (Mock Objects: Test Environment Only) and ADR-023 (Workspace-First Execution).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.memory.memory_adapter import _assert_test_environment

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        Artifact,
        ArtifactCollectionResult,
        IsolationHandle,
    )


class MemoryArtifactAdapter:
    """In-memory implementation of ArtifactCollectionPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates artifact collection without filesystem access.
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        _assert_test_environment()
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
