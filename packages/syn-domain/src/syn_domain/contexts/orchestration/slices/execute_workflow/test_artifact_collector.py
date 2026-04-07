"""Tests for ArtifactCollector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.artifacts._shared.value_objects import ArtifactType
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
    map_artifact_type,
)

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )


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
