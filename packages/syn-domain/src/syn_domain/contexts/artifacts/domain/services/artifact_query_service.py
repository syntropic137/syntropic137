"""Artifact Query Service - retrieves artifacts from projections.

This service provides a clean interface for querying artifacts,
particularly for phase-to-phase artifact injection in workflow execution.

See ADR-012: Artifact Storage Architecture
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from syn_domain.contexts.artifacts._shared.value_objects import ContentType, PhaseOutputFile
from syn_domain.contexts.artifacts.ports.ArtifactContentStoragePort import ArtifactStorageError

logger = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.contexts.artifacts.domain.read_models.artifact_summary import (
        ArtifactSummary,
    )
    from syn_domain.contexts.artifacts.ports.ArtifactContentStoragePort import (
        ArtifactContentStoragePort,
    )


def _as_instant(created: datetime | str | None) -> datetime | None:
    """A comparable UTC instant, or None if there isn't one.

    `created_at` is stored as either a datetime or an ISO string, and ISO
    strings do NOT sort chronologically: `...T10:00:00+02:00` (08:00Z)
    sorts after `...T09:00:00+00:00` (09:00Z) because "10" > "09". A naive
    value is read as UTC, which is what every writer here records.
    """
    if created is None:
        return None
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            return None
    if created.tzinfo is None:
        return created.replace(tzinfo=UTC)
    return created.astimezone(UTC)


def _is_binary(artifact: ArtifactSummary) -> bool:
    """Whether the row's bytes live in object storage only (#990).

    A type this build does not know is treated as text, which is what every
    row was before binary types existed.
    """
    try:
        return ContentType(artifact.content_type or ContentType.TEXT_MARKDOWN).is_binary
    except ValueError:
        return False


def _has_content(artifact: ArtifactSummary) -> bool:
    """Whether the row stands for a file that can be handed forward."""
    return bool(artifact.content) or _is_binary(artifact)


def _injection_rank(artifact: ArtifactSummary) -> tuple[int, int, datetime, str]:
    """Rank candidates for a phase's flat alias. Lower wins.

    Explicit primary first; then earliest-created, which reproduces what
    the live path chose for executions written before the flag existed.
    Rows with no usable timestamp sort last, and the artifact id is a
    final tiebreak so two such rows still resolve the same way on every
    query rather than falling back to row order.
    """
    primary = 0 if artifact.is_primary_deliverable else 1
    instant = _as_instant(artifact.created_at)
    if instant is None:
        return (primary, 1, _EPOCH, artifact.id)
    return (primary, 0, instant, artifact.id)


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

    async def get_files_for_artifacts(
        self,
        execution_id: str,
        phase_artifact_ids: Mapping[str, Sequence[str]],
    ) -> dict[str, list[PhaseOutputFile]]:
        """The files of exactly these artifacts of an execution, per phase.

        For a resume handing forward what it inherited (ADR-014 s7): the parent
        named the artifact ids each inherited phase kept, and an attempt it
        abandoned produced others under the same phase id. Selecting by phase
        would hand those over too; selecting by id cannot.

        Args:
            execution_id: The execution that produced the artifacts
            phase_artifact_ids: phase_id -> the artifact ids it kept

        Returns:
            Dict mapping phase_id -> those artifacts' files, ranked as
            ``get_files_for_phase_injection`` ranks them.
        """
        ...


class ArtifactQueryService:
    """Service for querying artifacts from the projection store.

    Replaces in-memory phase_outputs dict with DB-backed queries.
    """

    def __init__(
        self,
        projection: _ArtifactProjection,
        content_storage: ArtifactContentStoragePort | None = None,
    ) -> None:
        """Initialize with an artifact projection.

        Args:
            projection: The artifact projection to query (duck-typed)
            content_storage: Where a binary artifact's bytes are (#990). The
                read model holds text only, so without it a binary file is
                not handed forward on the restart path - and is logged.
        """
        self._projection = projection
        self._content_storage = content_storage

    async def _files(self, rows: list[ArtifactSummary]) -> list[PhaseOutputFile]:
        """The rows as files to hand forward, in injection rank order.

        Text comes from the read model as before. A binary row's content is
        empty there by design (Lane 1 holds no bytes), so its bytes are read
        from object storage, which is where the collector put them (#990).
        """
        files: list[PhaseOutputFile] = []
        for row in sorted(rows, key=_injection_rank):
            content = await self._content_of(row)
            if content is not None:
                files.append(PhaseOutputFile(source_path=row.source_path, content=content))
        return files

    async def _content_of(self, row: ArtifactSummary) -> str | bytes | None:
        if not _is_binary(row):
            return row.content
        if self._content_storage is None:
            logger.warning(
                "Binary artifact %s (%s) not handed forward: no object storage wired",
                row.id,
                row.source_path,
            )
            return None
        try:
            return await self._content_storage.download(row.id, storage_uri=row.storage_uri)
        except ArtifactStorageError as err:
            logger.warning(
                "Binary artifact %s (%s) not handed forward: %s", row.id, row.source_path, err
            )
            return None

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
            # Empty content is not a deliverable. `CreateArtifactCommand`
            # rejects it (min_length=1), the live cache skips it, and the
            # multi-file path skips it -- so the alias must too, or a
            # legacy/corrupt row could win here and appear nowhere else.
            if not artifact.content:
                continue
            incumbent = best.get(phase_id)
            if incumbent is None or _injection_rank(artifact) < _injection_rank(incumbent):
                best[phase_id] = artifact

        return {phase_id: a.content for phase_id, a in best.items() if a.content}

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
        by_phase: dict[str, list[ArtifactSummary]] = {}
        artifacts = await self._projection.get_by_execution(execution_id)

        for artifact in artifacts:
            phase_id = artifact.phase_id
            if (
                phase_id is None
                or phase_id not in completed_phase_ids
                or not _has_content(artifact)
            ):
                continue
            by_phase.setdefault(phase_id, []).append(artifact)

        # Same rank as the flat alias above, and for the same reason: row
        # order is not a selector. `ArtifactCollector._injectable` dedups by
        # destination path first-wins, so this list's order decides which
        # content survives a duplicated `source_path`. Since #1149 it also
        # takes the HEAD of this list as `<phase-id>.md`, so the ranking here
        # is what makes the alias and the tree name the same artifact.
        return {phase_id: await self._files(rows) for phase_id, rows in by_phase.items()}

    async def get_files_for_artifacts(
        self,
        execution_id: str,
        phase_artifact_ids: Mapping[str, Sequence[str]],
    ) -> dict[str, list[PhaseOutputFile]]:
        """The files of exactly these artifacts of an execution, per phase.

        Same filter and rank as `get_files_for_phase_injection`, so the head of
        each list is the artifact a live run would have handed forward as that
        phase's alias. The phase an artifact counts for is the one it was
        NAMED under, not the one its row records.
        """
        phase_of = {
            artifact_id: phase_id
            for phase_id, artifact_ids in phase_artifact_ids.items()
            for artifact_id in artifact_ids
        }
        by_phase: dict[str, list[ArtifactSummary]] = {}
        for artifact in await self._projection.get_by_execution(execution_id):
            phase_id = phase_of.get(artifact.id)
            if phase_id is None or not _has_content(artifact):
                continue
            by_phase.setdefault(phase_id, []).append(artifact)
        return {phase_id: await self._files(rows) for phase_id, rows in by_phase.items()}
