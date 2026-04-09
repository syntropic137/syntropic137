"""Artifact collection and injection for workflow execution.

Handles artifact lifecycle within a phase:
- Injecting artifacts from previous phases into workspace
- Collecting output artifacts from workspace after execution
- Creating artifact aggregates with two-tier storage (ADR-012)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from syn_domain.contexts.artifacts._shared.value_objects import ArtifactType

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.ports.artifact_storage import (
        ArtifactContentStoragePort,
    )
    from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
        ArtifactQueryServiceProtocol,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        ArtifactRepository,
    )


class ExecutionContext(Protocol):
    """Protocol for execution context needed by inject_from_previous_phases."""

    @property
    def execution_id(self) -> str: ...

    @property
    def completed_phase_ids(self) -> list[str]: ...

    @property
    def phase_outputs(self) -> dict[str, str]: ...


logger = logging.getLogger(__name__)


class ArtifactWorkspace(Protocol):
    """Protocol for workspace methods needed by ArtifactCollector."""

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None: ...

    async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]: ...


# Mapping from string artifact types to enum values
_ARTIFACT_TYPE_MAP: dict[str, ArtifactType] = {
    "text": ArtifactType.TEXT,
    "markdown": ArtifactType.MARKDOWN,
    "code": ArtifactType.CODE,
    "json": ArtifactType.JSON,
    "yaml": ArtifactType.YAML,
    "research_summary": ArtifactType.RESEARCH_SUMMARY,
    "plan": ArtifactType.PLAN,
    "execution_report": ArtifactType.EXECUTION_REPORT,
    "documentation": ArtifactType.DOCUMENTATION,
    "analysis_report": ArtifactType.ANALYSIS_REPORT,
    "requirements": ArtifactType.REQUIREMENTS,
    "design_doc": ArtifactType.DESIGN_DOC,
    "configuration": ArtifactType.CONFIGURATION,
    "script": ArtifactType.SCRIPT,
}


def map_artifact_type(type_str: str) -> ArtifactType:
    """Map string artifact type to enum."""
    return _ARTIFACT_TYPE_MAP.get(type_str.lower(), ArtifactType.OTHER)


@dataclass(frozen=True)
class CollectedArtifacts:
    """Result of collecting artifacts from a workspace."""

    artifact_ids: list[str]
    first_content: str | None


class ArtifactCollector:
    """Handles artifact injection and collection for phase execution."""

    def __init__(
        self,
        repository: ArtifactRepository,
        content_storage: ArtifactContentStoragePort | None,
        query_service: ArtifactQueryServiceProtocol | None,
    ) -> None:
        self._repository = repository
        self._content_storage = content_storage
        self._query_service = query_service

    async def inject_from_previous_phases(
        self,
        workspace: ArtifactWorkspace,
        ctx: ExecutionContext,
    ) -> None:
        """Inject input artifacts from previous phases into workspace.

        Writes files to artifacts/input/ in the workspace (ADR-036).
        Delegates to inject_from_previous_phases_explicit.
        """
        await self.inject_from_previous_phases_explicit(
            workspace=workspace,
            completed_phase_ids=ctx.completed_phase_ids,
            phase_outputs=ctx.phase_outputs,
            execution_id=ctx.execution_id,
        )

    async def inject_from_previous_phases_explicit(
        self,
        workspace: ArtifactWorkspace,
        completed_phase_ids: list[str],
        phase_outputs: dict[str, str],
        execution_id: str = "",
    ) -> None:
        """Inject artifacts using explicit parameters (ISS-196).

        Used by WorkspaceProvisionHandler in the Processor To-Do List pattern.
        """
        if not completed_phase_ids:
            return

        resolved = await self._resolve_phase_outputs(
            completed_phase_ids, phase_outputs, execution_id
        )
        await self._inject_and_log(workspace, resolved, completed_phase_ids)

    async def _resolve_phase_outputs(
        self,
        completed_phase_ids: list[str],
        phase_outputs: dict[str, str],
        execution_id: str,
    ) -> dict[str, str]:
        """Resolve phase outputs from cache, falling back to projection query."""
        resolved = {pid: phase_outputs[pid] for pid in completed_phase_ids if pid in phase_outputs}
        missing = [pid for pid in completed_phase_ids if pid not in resolved]
        if missing and self._query_service:
            projection_outputs = await self._query_service.get_for_phase_injection(
                execution_id=execution_id,
                completed_phase_ids=missing,
            )
            resolved.update(projection_outputs)
        return resolved

    @staticmethod
    async def _inject_and_log(
        workspace: ArtifactWorkspace,
        resolved_outputs: dict[str, str],
        completed_phase_ids: list[str],
    ) -> None:
        """Inject resolved outputs into workspace and log the result."""
        files_to_inject = [
            (f"artifacts/input/{phase_id}.md", content.encode())
            for phase_id, content in resolved_outputs.items()
        ]
        if files_to_inject:
            await workspace.inject_files(files_to_inject)
            logger.info(
                "Injected %d artifact(s) from previous phases: %s",
                len(files_to_inject),
                list(resolved_outputs.keys()),
            )
        elif completed_phase_ids:
            logger.warning(
                "No artifacts found for completed phases: %s",
                completed_phase_ids,
            )

    async def collect_from_workspace(
        self,
        workspace: ArtifactWorkspace,
        workflow_id: str,
        phase_id: str,
        execution_id: str,
        session_id: str,
        phase_name: str,
        output_artifact_type: str,
    ) -> CollectedArtifacts:
        """Collect output artifacts from workspace after execution.

        Collects from artifacts/output/ (ADR-036) and creates artifact aggregates.

        Returns:
            CollectedArtifacts with IDs and first artifact content for injection.
        """
        artifacts = await workspace.collect_files(
            patterns=["artifacts/output/**/*"],
        )

        artifact_ids: list[str] = []
        first_content: str | None = None

        for artifact_path, artifact_content in artifacts:
            artifact_id = str(uuid4())
            content_str = artifact_content.decode("utf-8", errors="replace")
            await self.create_artifact(
                artifact_id=artifact_id,
                workflow_id=workflow_id,
                phase_id=phase_id,
                execution_id=execution_id,
                session_id=session_id,
                artifact_type=output_artifact_type,
                content=content_str,
                title=f"{phase_name}: {artifact_path}",
            )
            artifact_ids.append(artifact_id)
            if first_content is None:
                first_content = content_str

        return CollectedArtifacts(
            artifact_ids=artifact_ids,
            first_content=first_content,
        )

    async def collect_partial(
        self,
        workspace: ArtifactWorkspace,
        workflow_id: str,
        phase_id: str,
        execution_id: str,
        session_id: str,
        phase_name: str,
        output_artifact_type: str,
    ) -> list[str]:
        """Collect partial artifacts during interrupt. Never raises."""
        try:
            partial_artifacts = await workspace.collect_files(patterns=["artifacts/output/**/*"])
            artifact_ids: list[str] = []
            for artifact_path, artifact_content in partial_artifacts:
                artifact_id = str(uuid4())
                content_str = artifact_content.decode("utf-8", errors="replace")
                await self.create_artifact(
                    artifact_id=artifact_id,
                    workflow_id=workflow_id,
                    phase_id=phase_id,
                    execution_id=execution_id,
                    session_id=session_id,
                    artifact_type=output_artifact_type,
                    content=content_str,
                    title=f"{phase_name} (partial): {artifact_path}",
                )
                artifact_ids.append(artifact_id)
            return artifact_ids
        except Exception as err:
            logger.warning(
                "Failed to collect partial artifacts for %s: %s",
                session_id,
                err,
            )
            return []

    async def create_artifact(
        self,
        artifact_id: str,
        workflow_id: str,
        phase_id: str,
        execution_id: str,
        session_id: str,
        artifact_type: str,
        content: str,
        title: str,
    ) -> None:
        """Create and save an artifact with two-tier storage (ADR-012)."""
        from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
            ArtifactAggregate,
        )
        from syn_domain.contexts.artifacts.domain.commands.CreateArtifactCommand import (
            CreateArtifactCommand,
        )

        artifact_type_enum = map_artifact_type(artifact_type)

        # Upload content to object storage if configured (ADR-012)
        storage_uri: str | None = None
        if self._content_storage is not None:
            try:
                result = await self._content_storage.upload(
                    artifact_id=artifact_id,
                    content=content.encode("utf-8"),
                    workflow_id=workflow_id,
                    phase_id=phase_id,
                    execution_id=execution_id,
                    content_type="text/markdown",
                    metadata={
                        "session_id": session_id,
                        "artifact_type": artifact_type,
                        "title": title,
                    },
                )
                storage_uri = result.storage_uri
                logger.info(
                    "Artifact content uploaded to object storage",
                    extra={
                        "artifact_id": artifact_id,
                        "storage_uri": storage_uri,
                        "size_bytes": result.size_bytes,
                    },
                )
            except Exception as e:
                logger.warning(
                    "Failed to upload artifact to object storage, "
                    "content will be stored in event store only",
                    extra={"artifact_id": artifact_id, "error": str(e)},
                )

        aggregate = ArtifactAggregate()
        command = CreateArtifactCommand(
            aggregate_id=artifact_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            execution_id=execution_id,
            session_id=session_id,
            artifact_type=artifact_type_enum,
            content=content,
            title=title,
            storage_uri=storage_uri,
        )
        aggregate._handle_command(command)
        await self._repository.save(aggregate)
