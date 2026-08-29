"""Artifact collection and injection for workflow execution.

Handles artifact lifecycle within a phase:
- Injecting artifacts from previous phases into workspace
- Collecting output artifacts from workspace after execution
- Creating artifact aggregates with two-tier storage (ADR-012)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, Protocol
from uuid import uuid4

from syn_domain.contexts.artifacts import ArtifactType, PhaseOutputFile
from syn_shared.workspace_paths import (
    WORKSPACE_INPUT_DIR,
    WORKSPACE_OUTPUT_DIR,
    WORKSPACE_ROOT,
)

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

#: ADR-036 workspace layout, expressed RELATIVE to the workspace root because
#: that is what ``collect_files``/``inject_files`` speak. Derived from the
#: shared absolute constants rather than re-typed, so a layout change is one
#: edit in ``syn_shared.workspace_paths`` and not a hunt through string
#: literals.
_OUTPUT_DIR_REL: Final[str] = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT).as_posix()
_INPUT_DIR_REL: Final[str] = WORKSPACE_INPUT_DIR.relative_to(WORKSPACE_ROOT).as_posix()

#: The glob a phase's deliverables are collected with.
_OUTPUT_GLOB: Final[str] = f"{_OUTPUT_DIR_REL}/**/*"

#: Extension of the flat single-file alias kept for one release (issue #988).
_FLAT_ALIAS_SUFFIX: Final[str] = ".md"


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
    """Result of collecting artifacts from a workspace.

    ``first_content`` is the phase's PRIMARY deliverable and feeds prompt
    substitution, which genuinely wants one string. ``files`` is the whole
    output tree and feeds the workspace handoff, which does not (issue #988).
    Before #988 only ``first_content`` existed, so the handoff inherited the
    prompt's shape and silently dropped every file but one.
    """

    artifact_ids: list[str]
    first_content: str | None
    files: list[PhaseOutputFile] = field(default_factory=list)


#: DIRECTORY names that hold machine-generated build output (issue #919).
#:
#: Deliberately narrow, and narrower than the first draft of this fix. Anything
#: under artifacts/output/ was explicitly designated a deliverable by the
#: workflow that wrote it, so the asymmetry is severe: keeping junk is
#: annoying and recoverable, DROPPING a real artifact is silent data loss on
#: the output path with nothing to notice it. A broader list would have eaten
#: a node_modules snapshot, a packaged .venv, or a `.git` directory shipped
#: deliberately as a reproducible repo, all of which are plausible outputs.
#:
#: So this covers only what was actually MEASURED as a problem: 28
#: .pytest_cache and 16 __pycache__ entries out of 98 artifacts. If another
#: kind of junk shows up in a real run, measure it and add it then.
_IGNORED_DIRECTORY_SEGMENTS: Final[frozenset[str]] = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
    }
)


def _is_collectable(artifact_path: str) -> bool:
    """Whether a collected path is a deliverable rather than build junk.

    Matches PARENT directory segments only, never the final filename. A file
    literally named ``__pycache__`` is a file somebody chose to emit, and this
    cannot tell a directory from a filename by string alone, so it does not
    try: only the segments that are unambiguously directories are considered.

    Measured before this existed: 44 of 98 artifacts, 45% of the store, were
    build caches. The cost was not storage. The list is ordered oldest-first,
    so the junk pushed real outputs off the first page and hid the very
    deliverables someone opened the list to find.
    """
    parent_segments = artifact_path.split("/")[:-1]
    return not any(segment in _IGNORED_DIRECTORY_SEGMENTS for segment in parent_segments)


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
        phase_files: dict[str, list[PhaseOutputFile]] | None = None,
    ) -> None:
        """Inject artifacts using explicit parameters (ISS-196).

        Used by WorkspaceProvisionHandler in the Processor To-Do List pattern.

        Args:
            workspace: The workspace being provisioned for the NEXT phase.
            completed_phase_ids: Every phase already finished, not just the last.
            phase_outputs: phase_id -> primary deliverable content. Feeds the
                flat ``artifacts/input/<phase-id>.md`` alias.
            execution_id: Used to re-query the projection after a restart.
            phase_files: phase_id -> that phase's whole output tree (#988).
                Omitted or missing a phase means "resolve it from the
                projection", which is the crash-recovery path.
        """
        if not completed_phase_ids:
            return

        resolved = await self._resolve_phase_outputs(
            completed_phase_ids, phase_outputs, execution_id
        )
        resolved_files = await self._resolve_phase_files(
            completed_phase_ids, phase_files or {}, execution_id
        )
        await self._inject_and_log(workspace, resolved, resolved_files, completed_phase_ids)

    async def _resolve_phase_files(
        self,
        completed_phase_ids: list[str],
        phase_files: dict[str, list[PhaseOutputFile]],
        execution_id: str,
    ) -> dict[str, list[PhaseOutputFile]]:
        """Resolve phase output trees from cache, falling back to the projection.

        Mirrors ``_resolve_phase_outputs``. The fallback matters because the
        in-process cache dies with the processor; without it a restart would
        hand the next phase the flat alias only and quietly lose the tree.
        """
        resolved = {pid: phase_files[pid] for pid in completed_phase_ids if pid in phase_files}
        missing = [pid for pid in completed_phase_ids if pid not in resolved]
        if missing and self._query_service:
            resolved.update(
                await self._query_service.get_files_for_phase_injection(
                    execution_id=execution_id,
                    completed_phase_ids=missing,
                )
            )
        return resolved

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

    @classmethod
    def _tree_files(
        cls,
        resolved_files: dict[str, list[PhaseOutputFile]],
        seen: set[str],
    ) -> list[tuple[str, bytes]]:
        """Every produced file that may safely be injected, as (path, bytes).

        Extracted from `_inject_and_log` rather than inlined: with the
        containment refusal added, that method crossed the cognitive-complexity
        threshold. Splitting on "which files are eligible" versus "write them"
        is the natural seam anyway - the eligibility rules are what carry the
        security argument and deserve to be readable on their own.

        Mutates `seen` so the flat alias emitted afterwards can skip a path this
        already claimed.
        """
        out: list[tuple[str, bytes]] = []
        for phase_id, produced_files in resolved_files.items():
            for produced in produced_files:
                if produced.source_path is None:
                    continue  # pre-v5 artifact: no path, alias only
                path = cls._tree_path(phase_id, produced.source_path)
                if path is None:
                    continue  # refused: would escape the workspace
                if path in seen:
                    continue
                seen.add(path)
                out.append((path, produced.content.encode()))
        return out

    @staticmethod
    def _tree_path(phase_id: str, source_path: str) -> str | None:
        """Where a produced file lands in the consuming phase's workspace.

        The phase id namespaces the tree so accumulating every earlier phase
        cannot collide - two phases may both emit ``deliverable.md``.

        Returns None for anything that would not land strictly beneath the
        phase's own directory. Both inputs are validated even though the phase
        id is now constrained at authoring time (`PhaseYamlDefinition.id`),
        because this is the SINK: `source_path` arrives from the projection on
        the recovery path, so a row written before that grammar existed - or
        corrupted since - reaches here without passing it. Validating only at
        the boundary protects new workflows and not old data.

        A dropped file is visible (the tree is short); an escaped write is not.
        """
        # An ABSOLUTE source_path does not escape - joining it collapses the
        # double slash and it lands under the phase directory as
        # `<phase-id>/etc/passwd`. Contained, but it silently becomes a nested
        # file the author never described, under a name they did not choose.
        # A source_path is by contract relative to the workspace, so an absolute
        # one means the contract is already broken; refuse rather than reshape.
        if source_path.startswith("/"):
            logger.warning(
                "Refusing to inject %r for phase %r: source paths are workspace-relative",
                source_path,
                phase_id,
            )
            return None

        relative = source_path.removeprefix(f"{_OUTPUT_DIR_REL}/")
        candidate = PurePosixPath(f"{_INPUT_DIR_REL}/{phase_id}/{relative}")

        if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            logger.warning(
                "Refusing to inject %r for phase %r: it would escape the workspace",
                source_path,
                phase_id,
            )
            return None
        # Belt and braces: even without a literal `..`, the result must still
        # sit under this phase's directory.
        expected_root = PurePosixPath(_INPUT_DIR_REL) / phase_id
        if not candidate.is_relative_to(expected_root):
            logger.warning(
                "Refusing to inject %r for phase %r: outside %s",
                source_path,
                phase_id,
                expected_root,
            )
            return None
        return str(candidate)

    @staticmethod
    def _flat_alias_path(phase_id: str) -> str:
        """The pre-#988 single-file name, kept as an alias for one release.

        Workflows written against ``artifacts/input/<phase-id>.md`` keep
        working while authors migrate to the directory form.
        """
        return f"{_INPUT_DIR_REL}/{phase_id}{_FLAT_ALIAS_SUFFIX}"

    @classmethod
    async def _inject_and_log(
        cls,
        workspace: ArtifactWorkspace,
        resolved_outputs: dict[str, str],
        resolved_files: dict[str, list[PhaseOutputFile]],
        completed_phase_ids: list[str],
    ) -> None:
        """Inject every earlier phase's output tree, plus the flat alias.

        Two shapes are written per phase (issue #988):

        * ``artifacts/input/<phase-id>/<path under artifacts/output/>`` - one
          entry per file the phase actually produced.
        * ``artifacts/input/<phase-id>.md`` - the primary deliverable under the
          pre-#988 name, so existing workflows keep reading.

        A file whose ``source_path`` is None predates ArtifactCreated v5. Its
        original path was never recorded, so it gets the flat alias only; the
        alternative would be inventing a path the author never chose.
        """
        files_to_inject: list[tuple[str, bytes]] = []
        seen: set[str] = set()

        for path, content in cls._tree_files(resolved_files, seen):
            files_to_inject.append((path, content))

        for phase_id, content in resolved_outputs.items():
            alias = cls._flat_alias_path(phase_id)
            if alias in seen:
                continue
            seen.add(alias)
            files_to_inject.append((alias, content.encode()))

        if files_to_inject:
            await workspace.inject_files(files_to_inject)
            logger.info(
                "Injected %d file(s) from previous phases: %s",
                len(files_to_inject),
                sorted(set(resolved_outputs) | set(resolved_files)),
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
        collected = await workspace.collect_files(
            patterns=[_OUTPUT_GLOB],
        )
        artifacts = [(path, body) for path, body in collected if _is_collectable(path)]

        artifact_ids: list[str] = []
        files: list[PhaseOutputFile] = []
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
                source_path=artifact_path,
            )
            artifact_ids.append(artifact_id)
            files.append(PhaseOutputFile(source_path=artifact_path, content=content_str))
            if first_content is None:
                first_content = content_str

        return CollectedArtifacts(
            artifact_ids=artifact_ids,
            first_content=first_content,
            files=files,
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
            # Same filter as the happy path: collect_partial is the interrupt
            # route and shares the pattern, so fixing only the other site would
            # leave every cancelled run still sweeping junk (issue #919).
            partial_collected = await workspace.collect_files(patterns=[_OUTPUT_GLOB])
            partial_artifacts = [
                (path, body) for path, body in partial_collected if _is_collectable(path)
            ]
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
                    source_path=artifact_path,
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
        source_path: str | None = None,
    ) -> None:
        """Create and save an artifact with two-tier storage (ADR-012).

        ``source_path`` is where the file sat under ``artifacts/output/``. It is
        recorded as a field rather than left implicit in ``title`` so the
        handoff can rebuild the tree without parsing a display string (#988).
        """
        from syn_domain.contexts.artifacts import (
            ArtifactAggregate,
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
            source_path=source_path,
            storage_uri=storage_uri,
        )
        aggregate.create_artifact(command)
        await self._repository.save(aggregate)
