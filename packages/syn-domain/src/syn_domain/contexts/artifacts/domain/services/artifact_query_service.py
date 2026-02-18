"""Artifact Query Service - retrieves artifacts from projections.

This service provides a clean interface for querying artifacts,
particularly for phase-to-phase artifact injection in workflow execution.

See ADR-012: Artifact Storage Architecture
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.read_models.artifact_summary import (
        ArtifactSummary,
    )


@runtime_checkable
class ArtifactQueryServiceProtocol(Protocol):
    """Protocol for querying artifacts.

    This abstraction allows the WorkflowExecutionEngine to query artifacts
    without depending directly on the projection implementation.
    """

    async def get_by_execution(
        self,
        execution_id: str,
    ) -> list[ArtifactSummary]:
        """Get all artifacts for a specific execution run.

        Args:
            execution_id: The workflow execution ID

        Returns:
            List of artifacts created during this execution
        """
        ...

    async def get_for_phase_injection(
        self,
        execution_id: str,
        completed_phase_ids: list[str],
    ) -> dict[str, str]:
        """Get artifacts from completed phases for prompt injection.

        This is the primary method for retrieving previous phase outputs
        to substitute into the current phase's prompt template.

        Args:
            execution_id: The workflow execution ID
            completed_phase_ids: List of phase IDs that have completed

        Returns:
            Dict mapping phase_id -> artifact content
        """
        ...


class ArtifactQueryService:
    """Service for querying artifacts from the projection store.

    Replaces in-memory phase_outputs dict with DB-backed queries.
    """

    def __init__(self, projection: Any) -> None:
        """Initialize with an artifact projection.

        Args:
            projection: The artifact projection to query (duck-typed)
        """
        self._projection = projection

    async def get_by_execution(
        self,
        execution_id: str,
    ) -> list[ArtifactSummary]:
        """Get all artifacts for a specific execution run.

        Args:
            execution_id: The workflow execution ID

        Returns:
            List of artifacts created during this execution
        """
        return await self._projection.get_by_execution(execution_id)

    async def get_for_phase_injection(
        self,
        execution_id: str,
        completed_phase_ids: list[str],
    ) -> dict[str, str]:
        """Get artifacts from completed phases for prompt injection.

        Queries the artifact projection for primary deliverables from
        completed phases and returns them as a dict for template substitution.

        Args:
            execution_id: The workflow execution ID
            completed_phase_ids: List of phase IDs that have completed

        Returns:
            Dict mapping phase_id -> artifact content
        """
        phase_outputs: dict[str, str] = {}

        # Query all artifacts for this execution
        artifacts = await self._projection.get_by_execution(execution_id)

        # Filter to completed phases and extract content
        for artifact in artifacts:
            # Use the first artifact found for each phase (primary deliverable)
            if (
                artifact.phase_id in completed_phase_ids
                and artifact.content
                and artifact.phase_id not in phase_outputs
            ):
                phase_outputs[artifact.phase_id] = artifact.content

        return phase_outputs
