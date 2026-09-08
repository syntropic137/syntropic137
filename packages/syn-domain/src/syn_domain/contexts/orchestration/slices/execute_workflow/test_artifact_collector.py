"""Tests for ArtifactCollector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.artifacts._shared.value_objects import ArtifactType, PhaseOutputFile
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
    map_artifact_type,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    PhaseProducedNoDeclaredOutputError,
)

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )

# CI selects with `pytest -m unit`; without this the whole module is collected
# by no job and can fail on main behind a green check (#825).
pytestmark = pytest.mark.unit


class TestMapArtifactType:
    def test_known_types(self) -> None:
        assert map_artifact_type("text") == ArtifactType.TEXT
        assert map_artifact_type("markdown") == ArtifactType.MARKDOWN
        assert map_artifact_type("code") == ArtifactType.CODE
        assert map_artifact_type("json") == ArtifactType.JSON

    def test_case_insensitive(self) -> None:
        assert map_artifact_type("TEXT") == ArtifactType.TEXT
        assert map_artifact_type("Markdown") == ArtifactType.MARKDOWN

    def test_unknown_type(self) -> None:
        assert map_artifact_type("unknown_type") == ArtifactType.OTHER


@dataclass
class MockWorkspace:
    injected_files: list[tuple[str, bytes]] = field(default_factory=list)
    collected_files: list[tuple[str, bytes]] = field(default_factory=list)

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None:
        self.injected_files.extend(files)

    async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]:
        return self.collected_files


@dataclass
class MockArtifactRepo:
    saved: list[ArtifactAggregate] = field(default_factory=list)

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def get_by_id(self, artifact_id: str) -> None:
        return None


@dataclass
class MockExecutionContext:
    workflow_id: str = "w1"
    execution_id: str = "e1"
    completed_phase_ids: list[str] = field(default_factory=list)
    phase_outputs: dict[str, str] = field(default_factory=dict)


class TestArtifactCollector:
    @pytest.mark.asyncio
    async def test_inject_no_previous_phases(self) -> None:
        collector = ArtifactCollector(MockArtifactRepo(), None, None)
        workspace = MockWorkspace()
        ctx = MockExecutionContext()
        await collector.inject_from_previous_phases(workspace, ctx)  # type: ignore[arg-type]
        assert workspace.injected_files == []

    @pytest.mark.asyncio
    async def test_inject_from_cache(self) -> None:
        collector = ArtifactCollector(MockArtifactRepo(), None, None)
        workspace = MockWorkspace()
        ctx = MockExecutionContext(
            completed_phase_ids=["p1"],
            phase_outputs={"p1": "content from p1"},
        )
        await collector.inject_from_previous_phases(workspace, ctx)  # type: ignore[arg-type]
        assert len(workspace.injected_files) == 1
        path, content = workspace.injected_files[0]
        assert path == "artifacts/input/p1.md"
        assert content == b"content from p1"

    @pytest.mark.asyncio
    async def test_collect_from_workspace(self) -> None:
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(
            collected_files=[
                ("artifacts/output/result.md", b"# Result"),
                ("artifacts/output/data.json", b'{"key": "value"}'),
            ]
        )
        result = await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Test Phase",
            output_artifact_types=("markdown",),
        )
        assert len(result.artifact_ids) == 2
        assert result.first_content == "# Result"
        assert len(repo.saved) == 2
        # #988: every collected file is reported with the path it occupied,
        # not just the first one's content.
        assert [(f.source_path, f.content) for f in result.files] == [
            ("artifacts/output/result.md", "# Result"),
            ("artifacts/output/data.json", '{"key": "value"}'),
        ]
        assert [a.source_path for a in repo.saved] == [
            "artifacts/output/result.md",
            "artifacts/output/data.json",
        ]

    @pytest.mark.asyncio
    async def test_collect_empty_workspace_when_nothing_was_declared(self) -> None:
        """An UNDECLARED phase may produce nothing - the #1167 true negative.

        The declaration is empty, so there is no contract to violate and the
        empty collection is returned rather than raised on. The paired failure
        case lives in TestADeclaredOutputMustBeProduced below; without both,
        the rule either does not bite or bites everything.
        """
        collector = ArtifactCollector(MockArtifactRepo(), None, None)
        workspace = MockWorkspace()
        result = await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Test Phase",
            output_artifact_types=(),
        )
        assert result.artifact_ids == []
        assert result.first_content is None
        assert result.files == []

    @pytest.mark.asyncio
    async def test_inject_from_query_service(self) -> None:
        """Test injection path that falls back to query service for missing phases."""
        queried: list[tuple[str, list[str]]] = []

        class MockQueryService:
            async def get_for_phase_injection(
                self, execution_id: str, completed_phase_ids: list[str]
            ) -> dict[str, str]:
                queried.append((execution_id, completed_phase_ids))
                return {"p2": "content from projection"}

            async def get_files_for_phase_injection(
                self,
                execution_id: str,
                completed_phase_ids: list[str],
            ) -> dict[str, list[PhaseOutputFile]]:
                # This execution predates ArtifactCreated v5, so no file
                # carries a source_path and only the flat alias is written.
                del execution_id, completed_phase_ids
                return {}

        collector = ArtifactCollector(MockArtifactRepo(), None, MockQueryService())  # type: ignore[arg-type]
        workspace = MockWorkspace()
        ctx = MockExecutionContext(
            completed_phase_ids=["p1", "p2"],
            phase_outputs={"p1": "cached content"},  # p2 missing from cache
        )
        await collector.inject_from_previous_phases(workspace, ctx)  # type: ignore[arg-type]
        assert len(workspace.injected_files) == 2
        # p1 from cache, p2 from query service
        paths = [f[0] for f in workspace.injected_files]
        assert "artifacts/input/p1.md" in paths
        assert "artifacts/input/p2.md" in paths
        assert len(queried) == 1
        assert queried[0] == ("e1", ["p2"])

    @pytest.mark.asyncio
    async def test_collect_partial_success(self) -> None:
        """Test successful partial artifact collection."""
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(
            collected_files=[("artifacts/output/partial.md", b"partial content")]
        )
        result = await collector.collect_partial(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Phase",
            output_artifact_types=("text",),
        )
        assert len(result) == 1
        assert len(repo.saved) == 1

    @pytest.mark.asyncio
    async def test_collect_partial_never_raises(self) -> None:
        class BrokenWorkspace:
            async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]:
                raise RuntimeError("disk full")

        collector = ArtifactCollector(MockArtifactRepo(), None, None)
        result = await collector.collect_partial(
            workspace=BrokenWorkspace(),
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Phase",
            output_artifact_types=("text",),
        )
        assert result == []


@pytest.mark.unit
class TestBuildJunkIsNotCollected:
    """Build junk must not become artifacts (issue #919).

    Measured on the dev stack: 44 of 98 artifacts (45%) were .pytest_cache or
    __pycache__. It is not merely noise. It pushes real deliverables off the
    first page of `syn artifacts list`, so the junk actively hides the outputs
    someone came to read, and it grows with every workflow that runs a test
    suite, which is most of them.
    """

    @pytest.mark.asyncio
    async def test_pytest_cache_and_pycache_are_skipped(self) -> None:
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(
            collected_files=[
                ("artifacts/output/result.md", b"# Result"),
                ("artifacts/output/.pytest_cache/CACHEDIR.TAG", b"Signature: 8a477f5"),
                ("artifacts/output/.pytest_cache/v/cache/nodeids", b"[]"),
                ("artifacts/output/__pycache__/mod.cpython-314.pyc", b"\x00\x00"),
                ("artifacts/output/pkg/__pycache__/other.pyc", b"\x00\x00"),
                ("artifacts/output/data.json", b'{"key": "value"}'),
            ]
        )

        result = await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Test Phase",
            output_artifact_types=("markdown",),
        )

        assert len(result.artifact_ids) == 2
        assert len(repo.saved) == 2

    @pytest.mark.asyncio
    async def test_the_first_real_output_is_still_the_injected_content(self) -> None:
        """first_content feeds the next phase. If junk sorts ahead of the real
        output, the next phase is handed a .pyc instead of the deliverable.
        """
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(
            collected_files=[
                ("artifacts/output/.pytest_cache/CACHEDIR.TAG", b"Signature: 8a477f5"),
                ("artifacts/output/result.md", b"# Real Result"),
            ]
        )

        result = await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Test Phase",
            output_artifact_types=("markdown",),
        )

        assert result.first_content == "# Real Result"

    @pytest.mark.asyncio
    async def test_partial_collection_skips_junk_too(self) -> None:
        """collect_partial is the interrupt path and uses the same pattern, so
        it inherits the same defect. Fixing only the happy path would leave
        every cancelled run still sweeping junk.
        """
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(
            collected_files=[
                ("artifacts/output/partial.md", b"# Partial"),
                ("artifacts/output/__pycache__/x.pyc", b"\x00"),
            ]
        )

        ids = await collector.collect_partial(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Test Phase",
            output_artifact_types=("markdown",),
        )

        assert len(ids) == 1

    @pytest.mark.asyncio
    async def test_a_legitimate_file_is_not_skipped_by_a_substring_match(self) -> None:
        """Guards the guard. Matching on a bare substring would drop a real
        deliverable whose name merely contains an ignored token.
        """
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(
            collected_files=[
                ("artifacts/output/how-we-fixed-the-pytest-cache.md", b"# Notes"),
                ("artifacts/output/pycache-design.md", b"# Design"),
            ]
        )

        result = await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Test Phase",
            output_artifact_types=("markdown",),
        )

        assert len(result.artifact_ids) == 2

    @pytest.mark.asyncio
    async def test_a_file_named_like_an_ignored_directory_is_kept(self) -> None:
        """Dropping a real deliverable is silent data loss; keeping junk is not.

        The check cannot tell a directory from a filename by string alone, so
        it only inspects PARENT segments. A file somebody deliberately emitted
        and named `__pycache__` is a deliverable, and an earlier draft of this
        fix would have eaten it.
        """
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(
            collected_files=[
                ("artifacts/output/__pycache__", b"a file, not a directory"),
                ("artifacts/output/.pytest_cache", b"also a file"),
            ]
        )

        result = await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Test Phase",
            output_artifact_types=("text",),
        )

        assert len(result.artifact_ids) == 2

    @pytest.mark.asyncio
    async def test_plausible_deliverables_are_not_swept(self) -> None:
        """artifacts/output/ contents were DESIGNATED outputs by the workflow
        that wrote them. A denylist wide enough to catch every build cache also
        catches deliberate ones: a dependency-audit snapshot, a packaged
        environment, a reproducible repo shipped on purpose.
        """
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(
            collected_files=[
                ("artifacts/output/audit/node_modules/left-pad/index.js", b"x"),
                ("artifacts/output/repro/.git/HEAD", b"ref: refs/heads/main"),
                ("artifacts/output/env/.venv/pyvenv.cfg", b"home = /usr"),
                ("artifacts/output/forensics/.cache/entry", b"x"),
            ]
        )

        result = await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Test Phase",
            output_artifact_types=("text",),
        )

        assert len(result.artifact_ids) == 4


class TestExactlyOnePrimaryDeliverable:
    """The collector marks the phase's primary deliverable (#997).

    Without the flag the cold path has nothing to select on and falls back
    to row order, which production returns as `updated_at DESC` -- the LAST
    file collected, not the first one the live path injects.
    """

    @pytest.mark.asyncio
    async def test_only_the_first_collected_file_is_primary(self) -> None:
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(
            collected_files=[
                ("artifacts/output/deliverable.md", b"# Plan"),
                ("artifacts/output/review.yaml", b"verdict: ok"),
                ("artifacts/output/notes.md", b"scratch"),
            ]
        )

        result = await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Planning",
            output_artifact_types=("markdown",),
        )

        assert [a.is_primary_deliverable for a in repo.saved] == [True, False, False]
        # The primary must be the same file the live path injects.
        assert result.first_content == "# Plan"

    @pytest.mark.asyncio
    async def test_a_single_file_is_still_primary(self) -> None:
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(collected_files=[("artifacts/output/only.md", b"# Only")])

        await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Planning",
            output_artifact_types=("markdown",),
        )

        assert [a.is_primary_deliverable for a in repo.saved] == [True]


class TestADeclaredOutputMustBeProduced:
    """#1167 at the collector, where the declaration meets what was written.

    The end-to-end proof that the run STOPS lives in
    tests/contexts/workflows/execute_workflow/test_processor_smoke.py. These
    pin the rule itself: which combinations of declaration and output are a
    contract violation, and which are ordinary.
    """

    @pytest.mark.asyncio
    async def test_declared_and_produced_nothing_raises(self) -> None:
        collector = ArtifactCollector(MockArtifactRepo(), None, None)

        with pytest.raises(PhaseProducedNoDeclaredOutputError) as excinfo:
            await collector.collect_from_workspace(
                workspace=MockWorkspace(),
                workflow_id="w1",
                phase_id="verify",
                execution_id="e1",
                session_id="s1",
                phase_name="Verify",
                output_artifact_types=("analysis_report",),
            )

        message = str(excinfo.value)
        assert "verify" in message, f"must name the phase, got {message!r}"
        assert "analysis_report" in message, f"must name what was missing, got {message!r}"

    @pytest.mark.asyncio
    async def test_a_workspace_holding_only_build_junk_counts_as_nothing(self) -> None:
        """Junk is not a deliverable, so declaring output and emitting only
        junk is the same violation as emitting nothing.

        Without this the rule is trivially evaded by any phase whose run
        happened to leave a __pycache__ behind - which, for a phase that ran
        Python at all, is most of them.
        """
        collector = ArtifactCollector(MockArtifactRepo(), None, None)
        workspace = MockWorkspace(
            collected_files=[("artifacts/output/__pycache__/mod.cpython-312.pyc", b"\x00")]
        )

        with pytest.raises(PhaseProducedNoDeclaredOutputError):
            await collector.collect_from_workspace(
                workspace=workspace,
                workflow_id="w1",
                phase_id="falsify",
                execution_id="e1",
                session_id="s1",
                phase_name="Falsify",
                output_artifact_types=("markdown",),
            )

    @pytest.mark.asyncio
    async def test_an_interrupted_phase_salvaging_nothing_does_not_raise(self) -> None:
        """collect_partial is the interrupt path and stays best-effort.

        An interrupted phase already has a verdict. Raising a contract
        violation over an empty salvage would overwrite "cancelled" with a
        misleading cause.
        """
        collector = ArtifactCollector(MockArtifactRepo(), None, None)

        ids = await collector.collect_partial(
            workspace=MockWorkspace(),
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Interrupted",
            output_artifact_types=("markdown",),
        )

        assert ids == []

    @pytest.mark.asyncio
    async def test_the_first_declared_type_tags_every_artifact(self) -> None:
        """A phase may declare several types; the artifact record carries one.

        Pinned because the narrowing MOVED in #1167 - it used to happen in
        ExecuteWorkflowHandler and now happens here. A tuple asserted with two
        entries could not pass under the old singular field.
        """
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        workspace = MockWorkspace(collected_files=[("artifacts/output/plan.md", b"# Plan")])

        await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Planning",
            output_artifact_types=("plan", "markdown"),
        )

        assert [a.artifact_type for a in repo.saved] == [ArtifactType.PLAN]


@pytest.mark.unit
class TestTheFlatAliasDerivesFromTheTree:
    """The alias and the tree come from ONE resolution (issue #1149).

    They used to be two: `_resolve_phase_files` fed
    `artifacts/input/<phase-id>/<path>` and a separate `_resolve_phase_outputs`
    fed `artifacts/input/<phase-id>.md`, each with its own cache-then-projection
    fallback. Nothing forced them to agree, so a phase could resolve as files
    and not as an output string, receive the tree, receive no alias, and every
    prompt reading the alias - half the corpus - found nothing and stopped with
    zero commands run. Three container sessions died that way.

    These drive the real collector and assert on what reaches the workspace,
    which is the only place the disagreement was ever visible.
    """

    @staticmethod
    async def _inject(
        *,
        phase_outputs: dict[str, str],
        phase_files: dict[str, list[PhaseOutputFile]] | None,
        query_service: object | None = None,
    ) -> dict[str, bytes]:
        collector = ArtifactCollector(MockArtifactRepo(), None, query_service)  # type: ignore[arg-type]
        workspace = MockWorkspace()
        await collector.inject_from_previous_phases_explicit(
            workspace=workspace,
            completed_phase_ids=["p1"],
            phase_outputs=phase_outputs,
            execution_id="e1",
            phase_files=phase_files,
        )
        return dict(workspace.injected_files)

    @pytest.mark.asyncio
    async def test_a_phase_resolved_from_the_projection_gets_both_shapes(self) -> None:
        """The reported incident, at the hop that showed it.

        The projection answers for the tree; the phase is absent from both
        halves of the in-process cache, which is what a restart looks like.
        Before #1149 the second resolution ran independently and could come
        back empty, and then only the tree was written.
        """

        class FilesOnlyQueryService:
            async def get_for_phase_injection(
                self, execution_id: str, completed_phase_ids: list[str]
            ) -> dict[str, str]:
                del execution_id, completed_phase_ids
                return {}

            async def get_files_for_phase_injection(
                self, execution_id: str, completed_phase_ids: list[str]
            ) -> dict[str, list[PhaseOutputFile]]:
                del execution_id, completed_phase_ids
                return {
                    "p1": [
                        PhaseOutputFile(
                            source_path="artifacts/output/deliverable.md",
                            content="# Findings\nthe real deliverable",
                        )
                    ]
                }

        injected = await self._inject(
            phase_outputs={},
            phase_files={},
            query_service=FilesOnlyQueryService(),
        )

        assert injected["artifacts/input/p1/deliverable.md"] == b"# Findings\nthe real deliverable"
        assert injected["artifacts/input/p1.md"] == b"# Findings\nthe real deliverable"

    @pytest.mark.asyncio
    async def test_a_phase_cached_as_files_only_gets_both_shapes(self) -> None:
        """The same divergence on the live path, with no projection at all.

        `PhaseOutputCache` records `primary` and `files` under separate
        truthiness checks, so the caller can hand over one without the other.
        """
        injected = await self._inject(
            phase_outputs={},
            phase_files={
                "p1": [
                    PhaseOutputFile(
                        source_path="artifacts/output/deliverable.md",
                        content="# Findings\nthe real deliverable",
                    )
                ]
            },
        )

        assert injected["artifacts/input/p1/deliverable.md"] == b"# Findings\nthe real deliverable"
        assert injected["artifacts/input/p1.md"] == b"# Findings\nthe real deliverable"

    @pytest.mark.asyncio
    async def test_when_the_two_sources_disagree_the_tree_wins(self) -> None:
        """Presence is not enough: the two shapes must name the same content.

        Both resolutions succeeding is the case the old code got least wrong
        and still got wrong - it wrote the tree from one source and the alias
        from the other, so a phase could read a deliverable at
        `<phase-id>.md` that no file under `<phase-id>/` matched. The stale
        string here cannot be the answer unless a second resolution still
        feeds the alias.
        """
        injected = await self._inject(
            phase_outputs={"p1": "STALE: a second resolution answered this"},
            phase_files={
                "p1": [
                    PhaseOutputFile(
                        source_path="artifacts/output/deliverable.md",
                        content="# Findings\nthe real deliverable",
                    )
                ]
            },
        )

        assert injected["artifacts/input/p1.md"] == b"# Findings\nthe real deliverable"
        assert injected["artifacts/input/p1.md"] == injected["artifacts/input/p1/deliverable.md"]

    @pytest.mark.asyncio
    async def test_the_alias_is_the_phases_primary_deliverable(self) -> None:
        """Which file of several stands for the phase.

        Both sources rank the primary deliverable first - `_injection_rank` on
        the projection path, collection order on the live one - so the alias is
        the head of the list, not an arbitrary member of it.
        """
        injected = await self._inject(
            phase_outputs={},
            phase_files={
                "p1": [
                    PhaseOutputFile(
                        source_path="artifacts/output/deliverable.md", content="the primary"
                    ),
                    PhaseOutputFile(
                        source_path="artifacts/output/review.yaml", content="findings: []"
                    ),
                ]
            },
        )

        assert injected["artifacts/input/p1.md"] == b"the primary"

    @pytest.mark.asyncio
    async def test_a_phase_that_produced_nothing_gets_neither_shape(self) -> None:
        """The alias must not appear for a phase with no resolvable output.

        Deriving it from the tree could have been implemented as "always write
        something", which would hand the next phase an empty file and turn a
        loud missing input into a silent empty one.
        """
        injected = await self._inject(phase_outputs={}, phase_files={"p1": []})

        assert injected == {}
