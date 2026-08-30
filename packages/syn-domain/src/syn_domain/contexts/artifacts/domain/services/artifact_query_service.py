"""Artifact Query Service - retrieves artifacts from projections.

This service provides a clean interface for querying artifacts,
particularly for phase-to-phase artifact injection in workflow execution.

See ADR-012: Artifact Storage Architecture
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from syn_domain.contexts.artifacts._shared.value_objects import PhaseOutputFile

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.read_models.artifact_summary import (
        ArtifactSummary,
    )


def _injection_rank(artifact: ArtifactSummary) -> tuple[int, int, str]:
    """Rank candidates for a phase's flat alias. Lower wins.

    Explicit primary first; then earliest-created, which reproduces what
    the live path chose for executions written before the flag existed.
    Rows with no timestamp sort last so a known time always beats none.
    """
    primary = 0 if artifact.is_primary_deliverable else 1
    created = artifact.created_at
    if created is None:
        return (primary, 1, "")
    stamp = created if isinstance(created, str) else created.isoformat()
    return (primary, 0, stamp)


class _ArtifactProjection(Protocol):
    """Protocol for the artifact projection dependency."""

    async def get_by_execution(self, execution_id: str) -> list[ArtifactSummary]: ...


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

    async def get_files_for_phase_injection(
        self,
        execution_id: str,
        completed_phase_ids: list[str],
    ) -> dict[str, list[PhaseOutputFile]]:
        """Get EVERY artifact from each completed phase, with its source path.

        The restart-safe counterpart to ``get_for_phase_injection``. That method
        returns one content string per phase, which is the right shape for
        prompt substitution and the wrong shape for reconstructing a phase's
        output directory (issue #988).

        Args:
            execution_id: The workflow execution ID
            completed_phase_ids: List of phase IDs that have completed

        Returns:
            Dict mapping phase_id -> every file that phase produced, in
            projection order. Files predating ArtifactCreated v5 carry a
            ``source_path`` of None.
        """
        ...


class ArtifactQueryService:
    """Service for querying artifacts from the projection store.

    Replaces in-memory phase_outputs dict with DB-backed queries.
    """

    def __init__(self, projection: _ArtifactProjection) -> None:
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
        artifacts = await self._projection.get_by_execution(execution_id)

        # Row order is NOT a selector (#997). The production store returns an
        # unordered query as `updated_at DESC` -- the LAST file collected --
        # while the live path injects the FIRST. Ranking instead makes both
        # paths agree, and keeps them agreeing after a restart.
        best: dict[str, ArtifactSummary] = {}
        for artifact in artifacts:
            phase_id = artifact.phase_id
            if phase_id is None or phase_id not in completed_phase_ids:
                continue
            if artifact.content is None:
                continue
            incumbent = best.get(phase_id)
            if incumbent is None or _injection_rank(artifact) < _injection_rank(incumbent):
                best[phase_id] = artifact

        return {phase_id: a.content for phase_id, a in best.items() if a.content is not None}

    async def get_files_for_phase_injection(
        self,
        execution_id: str,
        completed_phase_ids: list[str],
    ) -> dict[str, list[PhaseOutputFile]]:
        """Get every artifact from each completed phase, with its source path.

        Deliberately returns ALL artifacts per phase rather than the first
        (issue #988). ``get_for_phase_injection`` above keeps the first-only
        behaviour because its consumer - prompt substitution - genuinely wants
        one string; this one exists because the workspace handoff wants the
        whole tree, and collapsing it there silently dropped every file but one
        on the restart path.

        Args:
            execution_id: The workflow execution ID
            completed_phase_ids: List of phase IDs that have completed

        Returns:
            Dict mapping phase_id -> every file that phase produced.
        """
        phase_files: dict[str, list[PhaseOutputFile]] = {}
        artifacts = await self._projection.get_by_execution(execution_id)

        for artifact in artifacts:
            phase_id = artifact.phase_id
            if phase_id is None or phase_id not in completed_phase_ids or not artifact.content:
                continue
            phase_files.setdefault(phase_id, []).append(
                PhaseOutputFile(source_path=artifact.source_path, content=artifact.content)
            )

        return phase_files
