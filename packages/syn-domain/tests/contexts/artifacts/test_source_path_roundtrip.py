"""`source_path` must survive event -> projection -> query service (#988).

A phase outputs a directory. Rebuilding that directory in the next phase's
workspace after a processor restart requires the original relative path of each
file, and the ONLY durable record of it is the `source_path` field added in
ArtifactCreated v5. Before v5 the path existed only inside the display title
(`f"{phase_name}: {artifact_path}"`), recoverable only by splitting a
human-readable string on a separator a phase name may itself contain.

So this walks the whole restart path rather than any one hop: the aggregate
emits it, the projection persists it, and the query service hands it back
grouped per phase. A test of any single hop would pass while the value is
dropped in the next one.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.artifacts import (
    ArtifactAggregate,
    ArtifactType,
    CreateArtifactCommand,
    PhaseOutputFile,
)
from syn_domain.contexts.artifacts.domain.read_models.artifact_summary import (
    ArtifactSummary,
)
from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)

pytestmark = pytest.mark.unit

SOURCE_PATH = "artifacts/output/raw-findings/f1.yaml"


#: What ``ArtifactSummary.to_dict`` actually emits. Spelled out concretely
#: rather than as an opaque object-valued mapping, so the assertions below
#: type-check against real values.
ProjectionRow = dict[str, str | int | None]


class _Store:
    """Minimal projection store: records what the projection wrote."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectionRow] = {}

    async def save(self, _name: str, key: str, data: ProjectionRow) -> None:
        self.rows[key] = data


class _Projection:
    """Stands in for the real projection's read side."""

    def __init__(self, artifacts: list[ArtifactSummary]) -> None:
        self._artifacts = artifacts

    async def get_by_execution(self, _execution_id: str) -> list[ArtifactSummary]:
        return list(self._artifacts)


def _summary(
    artifact_id: str,
    phase_id: str,
    source_path: str | None,
    content: str,
) -> ArtifactSummary:
    return ArtifactSummary(
        id=artifact_id,
        workflow_id="wf-1",
        execution_id="exec-1",
        session_id=None,
        phase_id=phase_id,
        artifact_type="markdown",
        name=f"Phase One: {source_path}",
        created_at=None,
        content=content,
        source_path=source_path,
    )


class TestTheEventCarriesTheSourcePath:
    def test_create_artifact_records_the_source_path_on_the_event(self) -> None:
        aggregate = ArtifactAggregate()
        aggregate.create_artifact(
            CreateArtifactCommand(
                aggregate_id="art-1",
                workflow_id="wf-1",
                phase_id="phase-1",
                artifact_type=ArtifactType.MARKDOWN,
                content="id: f1",
                title="Phase One: " + SOURCE_PATH,
                source_path=SOURCE_PATH,
            )
        )
        assert aggregate.source_path == SOURCE_PATH

    def test_an_artifact_created_without_one_reports_none(self) -> None:
        """Pre-v5 shape. None must stay None rather than become "" or a guess -
        downstream distinguishes "no path recorded" from "path is empty"."""
        aggregate = ArtifactAggregate()
        aggregate.create_artifact(
            CreateArtifactCommand(
                aggregate_id="art-2",
                workflow_id="wf-1",
                phase_id="phase-1",
                artifact_type=ArtifactType.MARKDOWN,
                content="legacy",
                title="Phase One",
            )
        )
        assert aggregate.source_path is None


class TestTheProjectionPersistsIt:
    async def test_source_path_is_written_to_the_read_model(self) -> None:
        store = _Store()
        projection = ArtifactListProjection(store)
        await projection.on_artifact_created(
            {
                "artifact_id": "art-1",
                "workflow_id": "wf-1",
                "execution_id": "exec-1",
                "phase_id": "phase-1",
                "artifact_type": "markdown",
                "title": "Phase One: " + SOURCE_PATH,
                "content": "id: f1",
                "source_path": SOURCE_PATH,
            }
        )
        assert store.rows["art-1"]["source_path"] == SOURCE_PATH

    async def test_a_pre_v5_event_projects_a_null_source_path(self) -> None:
        """Deserialization resolves on event TYPE and ignores the stored
        version, so no upcaster runs and a v4 payload simply lacks the key."""
        store = _Store()
        projection = ArtifactListProjection(store)
        await projection.on_artifact_created(
            {
                "artifact_id": "art-2",
                "workflow_id": "wf-1",
                "execution_id": "exec-1",
                "phase_id": "phase-1",
                "artifact_type": "markdown",
                "title": "Phase One",
                "content": "legacy",
            }
        )
        assert store.rows["art-2"]["source_path"] is None

    def test_the_read_model_round_trips_source_path_through_a_dict(self) -> None:
        """The projection store persists dicts, so a field the read model can
        write but not read back is lost on the restart path specifically."""
        original = _summary("art-1", "phase-1", SOURCE_PATH, "id: f1")
        assert ArtifactSummary.from_dict(original.to_dict()).source_path == SOURCE_PATH


class TestTheQueryServiceReturnsEveryFilePerPhase:
    async def test_all_artifacts_for_a_phase_are_returned(self) -> None:
        """The restart path. `get_for_phase_injection` keeps only the first
        artifact per phase; if the file-oriented method did the same, a
        processor restart would silently drop the rest of the tree."""
        service = ArtifactQueryService(
            _Projection(
                [
                    _summary("a1", "phase-1", "artifacts/output/deliverable.md", "d"),
                    _summary("a2", "phase-1", "artifacts/output/review.yaml", "r"),
                    _summary("a3", "phase-1", SOURCE_PATH, "f"),
                ]
            )
        )
        files = await service.get_files_for_phase_injection("exec-1", ["phase-1"])
        assert [f.source_path for f in files["phase-1"]] == [
            "artifacts/output/deliverable.md",
            "artifacts/output/review.yaml",
            SOURCE_PATH,
        ]
        assert [f.content for f in files["phase-1"]] == ["d", "r", "f"]

    async def test_phases_are_kept_separate(self) -> None:
        service = ArtifactQueryService(
            _Projection(
                [
                    _summary("a1", "phase-1", "artifacts/output/deliverable.md", "one"),
                    _summary("a2", "phase-2", "artifacts/output/deliverable.md", "two"),
                ]
            )
        )
        files = await service.get_files_for_phase_injection("exec-1", ["phase-1", "phase-2"])
        assert files["phase-1"][0].content == "one"
        assert files["phase-2"][0].content == "two"

    async def test_uncompleted_phases_are_excluded(self) -> None:
        service = ArtifactQueryService(
            _Projection(
                [
                    _summary("a1", "phase-1", "artifacts/output/a.md", "one"),
                    _summary("a2", "phase-9", "artifacts/output/b.md", "nine"),
                ]
            )
        )
        files = await service.get_files_for_phase_injection("exec-1", ["phase-1"])
        assert set(files) == {"phase-1"}

    async def test_empty_content_is_skipped(self) -> None:
        service = ArtifactQueryService(
            _Projection(
                [
                    _summary("a1", "phase-1", "artifacts/output/empty.md", ""),
                    _summary("a2", "phase-1", "artifacts/output/real.md", "real"),
                ]
            )
        )
        files = await service.get_files_for_phase_injection("exec-1", ["phase-1"])
        assert [f.content for f in files["phase-1"]] == ["real"]

    async def test_a_pre_v5_artifact_comes_back_with_no_path(self) -> None:
        """It reaches the caller rather than being dropped; the caller decides
        that "no path" means the flat alias."""
        service = ArtifactQueryService(_Projection([_summary("a1", "phase-1", None, "legacy")]))
        files = await service.get_files_for_phase_injection("exec-1", ["phase-1"])
        assert files["phase-1"] == [PhaseOutputFile(source_path=None, content="legacy")]
