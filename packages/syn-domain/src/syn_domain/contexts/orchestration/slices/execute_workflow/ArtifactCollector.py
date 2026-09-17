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
from syn_domain.contexts.orchestration.slices.execute_workflow.artifact_recovery import (
    RECOVERED_SOURCE_PATH,
    DescribeWork,
    RecoveredArtifact,
    is_storable,
    recover_deliverable,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    EmptyPhaseArtifactError,
    PhaseProducedNoDeclaredOutputError,
)
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


async def _where_the_work_is(describe_work: DescribeWork | None) -> str | None:
    """Ask where this phase's work stands, tolerating an inspection that fails.

    A salvage runs on a phase that has already gone wrong once. An inspection
    that raised here would turn a recoverable incident into an unrecoverable
    one - the conclusion was in hand and would be discarded by the very code
    trying to save it - so a failed reading becomes no reading, which is what
    `None` already means to the caller.
    """
    if describe_work is None:
        return None
    try:
        return await describe_work()
    except Exception:
        logger.warning("Could not read where the phase's work stands", exc_info=True)
        return None


#: What an artifact is tagged as when its phase declared no type at all.
_UNDECLARED_ARTIFACT_TYPE: Final[str] = "text"


def _primary_type(declared: tuple[str, ...]) -> str:
    """The single type every artifact this phase produced is tagged with.

    A phase may declare several output types but the artifact record carries
    one, so the first declaration wins. This is the ONLY place the plural
    declaration is narrowed to a singular tag; it used to happen four hops
    earlier, in ExecuteWorkflowHandler, which is why "declared nothing" and
    "declared text" arrived here indistinguishable and no enforcement was
    possible (#1167).
    """
    return declared[0] if declared else _UNDECLARED_ARTIFACT_TYPE


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


@dataclass(frozen=True)
class _Deliverable:
    """One thing a phase delivered, ready to store, whatever route it came by.

    Exists so the storage loop cannot tell a written file from a recovered one
    and therefore cannot treat them differently by accident. Every field it
    needs is decided before the loop begins.
    """

    source_path: str
    content: str
    title: str

    @classmethod
    def of(cls, recovered: RecoveredArtifact) -> _Deliverable:
        """The recovered artifact as something to store, with nothing reworded."""
        return cls(
            source_path=recovered.source_path,
            content=recovered.content,
            title=recovered.title,
        )


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
            phase_outputs: phase_id -> primary deliverable content, the
                pre-#988 cache shape. Used only for a phase whose output tree
                is unknown, and then it IS that phase's tree - a single file
                whose path was never recorded.
            execution_id: Used to re-query the projection after a restart.
            phase_files: phase_id -> that phase's whole output tree (#988).
                Omitted or missing a phase means "resolve it from the
                projection", which is the crash-recovery path.
        """
        if not completed_phase_ids:
            return

        resolved = await self._resolve_phase_outputs(
            completed_phase_ids, phase_files or {}, phase_outputs, execution_id
        )
        await self._inject_and_log(workspace, resolved, completed_phase_ids)

    async def _resolve_phase_outputs(
        self,
        completed_phase_ids: list[str],
        phase_files: dict[str, list[PhaseOutputFile]],
        phase_outputs: dict[str, str],
        execution_id: str,
    ) -> dict[str, list[PhaseOutputFile]]:
        """What each completed phase produced. The single authority (#1149).

        Every shape the next workspace receives is derived from this one
        answer. There used to be a second resolution, for the flat alias
        alone, with its own cache-then-projection fallback; nothing forced
        the two to agree and they did not have to fail together, so a phase
        could resolve as files and not as an output string and arrive with a
        tree and no alias.

        Sources in order of how much they know, first hit wins per phase:
        the caller's file cache, the projection, then the caller's pre-#988
        primary string. The last is a tree of one file with no recorded path
        - the same shape a pre-v5 artifact has, and it reaches the next phase
        the same way, through the alias only.

        The projection is not asked for the alias separately because it
        cannot answer differently: ``get_files_for_phase_injection`` applies
        the same filter and the same ``_injection_rank`` as
        ``get_for_phase_injection`` and returns the latter's answer as its
        first entry.
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
        for phase_id in completed_phase_ids:
            if phase_id not in resolved and phase_id in phase_outputs:
                resolved[phase_id] = [
                    PhaseOutputFile(source_path=None, content=phase_outputs[phase_id])
                ]
        return resolved

    @classmethod
    def _injectable(
        cls,
        phase_id: str,
        produced: list[PhaseOutputFile],
        seen: set[str],
    ) -> list[tuple[str, bytes]]:
        """Everything one completed phase contributes, as (path, bytes).

        BOTH shapes come from the one list, which is the whole point of
        #1149: the tree is every file whose path was recorded, and the flat
        alias is the head of the same list. Deriving them together is what
        makes "the tree exists but the alias does not" unrepresentable rather
        than merely unlikely.

        A file whose ``source_path`` is None predates ArtifactCreated v5, or
        arrived as a bare pre-#988 primary string. Its path was never
        recorded, so it reaches the next phase through the alias only;
        inventing a path the author never chose is worse.

        Mutates ``seen``: the first write to a path wins, across phases.
        """
        out: list[tuple[str, bytes]] = []
        for produced_file in produced:
            if produced_file.source_path is None:
                continue  # path unknown: this one travels as the alias
            path = cls._tree_path(phase_id, produced_file.source_path)
            if path is None:
                continue  # refused: would escape the workspace
            if path in seen:
                continue
            seen.add(path)
            out.append((path, produced_file.content.encode()))

        primary = cls._primary_deliverable(produced)
        alias = cls._flat_alias_path(phase_id)
        if primary is not None and alias not in seen:
            seen.add(alias)
            out.append((alias, primary.encode()))
        return out

    @staticmethod
    def _primary_deliverable(produced: list[PhaseOutputFile]) -> str | None:
        """The one file that stands for the phase, or None if it produced none.

        The head of the list, because both sources put the primary
        deliverable there: the projection sorts by ``_injection_rank``, which
        ranks the explicitly-flagged primary first (#997), and the live path
        collects in the order it flagged. Choosing here by any other rule
        would recreate the disagreement #1149 removed, one layer down.

        Empty content is not a deliverable - `CreateArtifactCommand` rejects
        it and every other reader skips it, so a legacy or corrupt row cannot
        become the alias.
        """
        return next((f.content for f in produced if f.content), None)

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
        resolved: dict[str, list[PhaseOutputFile]],
        completed_phase_ids: list[str],
    ) -> None:
        """Inject every earlier phase's output tree, plus the flat alias.

        Two shapes are written per phase (issue #988):

        * ``artifacts/input/<phase-id>/<path under artifacts/output/>`` - one
          entry per file the phase actually produced.
        * ``artifacts/input/<phase-id>.md`` - the primary deliverable under the
          pre-#988 name, so existing workflows keep reading.

        Both are derived from ``resolved``, per phase, so a phase that
        contributes one contributes the other.
        """
        files_to_inject: list[tuple[str, bytes]] = []
        seen: set[str] = set()

        for phase_id, produced in resolved.items():
            files_to_inject.extend(cls._injectable(phase_id, produced, seen))

        if files_to_inject:
            await workspace.inject_files(files_to_inject)
            logger.info(
                "Injected %d file(s) from previous phases: %s",
                len(files_to_inject),
                sorted(resolved),
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
        output_artifact_types: tuple[str, ...],
        last_agent_message: str | None = None,
        describe_work: DescribeWork | None = None,
    ) -> CollectedArtifacts:
        """Collect a phase's declared output from its workspace, or fail.

        Collects from artifacts/output/ (ADR-036) and creates artifact
        aggregates. `output_artifact_types` is what the phase's workflow
        definition PROMISED it would produce.

        A phase that promised output and delivered none does not advance on
        silence. Before #1167 it returned empty here and the execution carried
        on as though the phase had succeeded, so a `verify` phase could drop
        out of a run while every surface still reported completed.

        But "delivered none" is about the deliverable, not about the file.
        `last_agent_message` is the last thing the phase's agent said on its
        own stream, and it is consulted whenever the deliverable is not
        readable from disk - the file was empty (#1195) or no collectable file
        was written at all (#1300). Both salvage the same way and both say so
        in the stored artifact's title and first line. Only when BOTH routes
        are empty does the phase fail, and then it fails naming which route was
        missing.

        `describe_work` says where the phase's branches stand and is asked ONLY
        when salvaging, because a salvaged phase does not fail and so never
        reaches the failure path that otherwise reports this (#1200). Its
        answer goes into the artifact, which is then the only record of where
        the surviving work is.

        Raises:
            PhaseProducedNoDeclaredOutputError: the phase declared output
                artifact types, produced none of them, and said nothing on its
                stream to recover either.
            EmptyPhaseArtifactError: the phase wrote a file with no content and
                nothing could be recovered from its transcript either.

        Returns:
            CollectedArtifacts with IDs and first artifact content for injection.
        """
        collected = await workspace.collect_files(
            patterns=[_OUTPUT_GLOB],
        )
        artifacts = [(path, body) for path, body in collected if _is_collectable(path)]

        deliverables = await self._deliverables(
            artifacts=artifacts,
            output_artifact_types=output_artifact_types,
            phase_id=phase_id,
            phase_name=phase_name,
            last_agent_message=last_agent_message,
            describe_work=describe_work,
        )

        artifact_type = _primary_type(output_artifact_types)
        artifact_ids: list[str] = []
        files: list[PhaseOutputFile] = []
        first_content: str | None = None

        for index, deliverable in enumerate(deliverables):
            artifact_id = str(uuid4())
            await self.create_artifact(
                artifact_id=artifact_id,
                workflow_id=workflow_id,
                phase_id=phase_id,
                execution_id=execution_id,
                session_id=session_id,
                artifact_type=artifact_type,
                content=deliverable.content,
                title=deliverable.title,
                source_path=deliverable.source_path,
                # The flat `<phase-id>.md` alias reads this after a restart,
                # so it must name the file the live path injects (#997).
                is_primary_deliverable=index == 0,
            )
            artifact_ids.append(artifact_id)
            files.append(
                PhaseOutputFile(
                    source_path=deliverable.source_path,
                    content=deliverable.content,
                )
            )
            if first_content is None:
                first_content = deliverable.content

        return CollectedArtifacts(
            artifact_ids=artifact_ids,
            first_content=first_content,
            files=files,
        )

    @staticmethod
    async def _deliverables(
        *,
        artifacts: list[tuple[str, bytes]],
        output_artifact_types: tuple[str, ...],
        phase_id: str,
        phase_name: str,
        last_agent_message: str | None,
        describe_work: DescribeWork | None,
    ) -> list[_Deliverable]:
        """What this phase actually delivered, whatever route it arrived by.

        The single place that decides between the three states a phase can be
        in; the caller above only stores what comes back. Splitting the
        decision across the storage loop is what let #1300 exist: the empty
        file was salvaged inside the loop and "no file" was refused before the
        loop was ever reached, so the two incidents were answered by different
        code that had no reason to agree.

        Whichever route the content came by, a recovered deliverable is stored
        marked - `recover_deliverable` owns the title, the banner and the path,
        so there is one description of "recovered" and not two.
        """
        # Judged on COLLECTABLE files, not on what the glob returned: a phase
        # whose entire output tree was build junk produced no deliverable, and
        # that is the same incident as writing nothing at all.
        if output_artifact_types and not artifacts:
            recovered = recover_deliverable(
                last_agent_message=last_agent_message,
                wrote=None,
                title=f"{phase_name}: {RECOVERED_SOURCE_PATH}",
                work=await _where_the_work_is(describe_work),
            )
            if recovered is None:
                raise PhaseProducedNoDeclaredOutputError(
                    phase_id=phase_id,
                    phase_name=phase_name,
                    declared=output_artifact_types,
                )
            logger.warning(
                "Phase %s (%s) declared %s and wrote no collectable file; recovered "
                "its conclusion from the session transcript instead of discarding "
                "the execution (#1300)",
                phase_id,
                phase_name,
                ", ".join(output_artifact_types),
            )
            return [_Deliverable.of(recovered)]

        deliverables: list[_Deliverable] = []
        for artifact_path, artifact_content in artifacts:
            content_str = artifact_content.decode("utf-8", errors="replace")
            title = f"{phase_name}: {artifact_path}"
            if is_storable(content_str):
                deliverables.append(
                    _Deliverable(source_path=artifact_path, content=content_str, title=title)
                )
                continue
            recovered = recover_deliverable(
                last_agent_message=last_agent_message,
                wrote=artifact_path,
                title=title,
                work=await _where_the_work_is(describe_work),
            )
            # Deliberately raises rather than skipping the file. Skipping would
            # put the execution back where #1167 found it - advancing past a
            # phase whose declared output never materialised - and the whole
            # value of failing here is that it is now a NAMED incident rather
            # than a schema complaint.
            if recovered is None:
                raise EmptyPhaseArtifactError(
                    phase_id=phase_id,
                    phase_name=phase_name,
                    source_path=artifact_path,
                )
            logger.warning(
                "Phase %s (%s) wrote an empty %s; recovered its content from the "
                "session transcript instead of failing the execution (#1195)",
                phase_id,
                phase_name,
                artifact_path,
            )
            deliverables.append(_Deliverable.of(recovered))
        return deliverables

    async def collect_partial(
        self,
        workspace: ArtifactWorkspace,
        workflow_id: str,
        phase_id: str,
        execution_id: str,
        session_id: str,
        phase_name: str,
        output_artifact_types: tuple[str, ...],
    ) -> list[str]:
        """Collect whatever an interrupted phase managed to write. Never raises.

        Deliberately does NOT enforce the output contract that
        `collect_from_workspace` enforces. An interrupted phase is already
        failing or cancelled, and its outcome is decided by the interrupt; the
        only question left here is how much of its work can be salvaged.
        Raising on an empty salvage would replace a truthful "cancelled" with a
        misleading "contract violated" and lose the real reason (#1167).
        """
        try:
            # Same filter as the happy path: collect_partial is the interrupt
            # route and shares the pattern, so fixing only the other site would
            # leave every cancelled run still sweeping junk (issue #919).
            partial_collected = await workspace.collect_files(patterns=[_OUTPUT_GLOB])
            partial_artifacts = [
                (path, body) for path, body in partial_collected if _is_collectable(path)
            ]
            artifact_type = _primary_type(output_artifact_types)
            artifact_ids: list[str] = []
            for artifact_path, artifact_content in partial_artifacts:
                artifact_id = str(uuid4())
                content_str = artifact_content.decode("utf-8", errors="replace")
                if not is_storable(content_str):
                    # SKIPPED, not recovered and not raised. This is the same
                    # empty-file shape as #1195, but on the interrupt path the
                    # outcome is already decided by the interrupt: there is no
                    # verdict to rescue, and substituting the transcript would
                    # invent a deliverable for a run nobody is going to read as
                    # one. What it does fix is that the store's refusal used to
                    # escape into the `except` below and abandon every
                    # REMAINING file, so one empty file cost the whole salvage.
                    logger.info(
                        "Skipping empty partial artifact %s for %s",
                        artifact_path,
                        session_id,
                    )
                    continue
                await self.create_artifact(
                    artifact_id=artifact_id,
                    workflow_id=workflow_id,
                    phase_id=phase_id,
                    execution_id=execution_id,
                    session_id=session_id,
                    artifact_type=artifact_type,
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
        is_primary_deliverable: bool = True,
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
            is_primary_deliverable=is_primary_deliverable,
        )
        aggregate.create_artifact(command)
        await self._repository.save(aggregate)
