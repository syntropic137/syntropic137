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
            output_artifact_type="markdown",
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
    async def test_collect_empty_workspace(self) -> None:
        collector = ArtifactCollector(MockArtifactRepo(), None, None)
        workspace = MockWorkspace()
        result = await collector.collect_from_workspace(
            workspace=workspace,
            workflow_id="w1",
            phase_id="p1",
            execution_id="e1",
            session_id="s1",
            phase_name="Test Phase",
            output_artifact_type="text",
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
            output_artifact_type="text",
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
            output_artifact_type="text",
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
            output_artifact_type="markdown",
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
            output_artifact_type="markdown",
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
            output_artifact_type="markdown",
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
            output_artifact_type="markdown",
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
            output_artifact_type="text",
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
            output_artifact_type="text",
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
            output_artifact_type="markdown",
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
            output_artifact_type="markdown",
        )

        assert [a.is_primary_deliverable for a in repo.saved] == [True]
