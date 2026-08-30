"""`is_primary_deliverable` must survive event -> projection -> query (#997).

The flat `artifacts/input/<phase-id>.md` alias is selected from this flag on
the cold path. The flag already existed on the command, the event and the
aggregate -- but `on_artifact_created` did not copy it into the read model,
so every projected row read back as primary and the cold path silently fell
back to row order. That is the divergence #997 exists to close, and it
survived a fix plus five tests because those tests hand-constructed
`ArtifactSummary` objects and never crossed the projection boundary.

So this walks the whole restart path rather than any single hop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.artifacts import (
    ArtifactAggregate,
    ArtifactType,
    CreateArtifactCommand,
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

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.unit

#: What `ArtifactSummary.to_dict` emits, and what the inner payload of a
#: dumped `ArtifactCreated` carries. Spelled out concretely rather than
#: `object`-valued so the assertions type-check against real values.
ProjectionRow = dict[str, str | int | bool | None]
EventPayload = dict[str, str | int | bool | None]


class _Store:
    """Minimal projection store: records what the projection wrote."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectionRow] = {}

    async def save(self, _name: str, key: str, data: ProjectionRow) -> None:
        self.rows[key] = data


class _ReadsBack:
    """Reads rows back the way the real store does: as dicts, reversed.

    Reversed because production returns an unordered query as
    `updated_at DESC`, so the LAST row written comes back first.
    """

    def __init__(self, store: _Store) -> None:
        self._store = store

    async def get_by_execution(self, _execution_id: str) -> list[ArtifactSummary]:
        rows: Iterable[ProjectionRow] = reversed(list(self._store.rows.values()))
        return [ArtifactSummary.from_dict(dict(r)) for r in rows]


def _created_event(artifact_id: str, content: str, *, is_primary: bool) -> EventPayload:
    """The event payload the aggregate emits, via the aggregate itself.

    Built through `ArtifactAggregate` rather than hand-written, so a field
    the command stops carrying fails here instead of passing against a
    literal that no longer matches production.
    """
    aggregate = ArtifactAggregate()
    aggregate.create_artifact(
        CreateArtifactCommand(
            aggregate_id=artifact_id,
            workflow_id="wf-1",
            execution_id="exec-1",
            session_id="sess-1",
            phase_id="research",
            artifact_type=ArtifactType.MARKDOWN,
            content=content,
            title=f"Research: {artifact_id}",
            is_primary_deliverable=is_primary,
        )
    )
    # The stored event is an envelope; the projection receives the inner
    # payload, so unwrap exactly as the dispatcher does.
    envelope = aggregate.get_uncommitted_events()[0].model_dump()
    payload = envelope["event"]
    assert isinstance(payload, dict)
    return payload


class TestTheProjectionPersistsTheFlag:
    async def test_a_secondary_artifact_does_not_project_as_primary(self) -> None:
        store = _Store()
        projection = ArtifactListProjection(store)

        await projection.on_artifact_created(
            _created_event("art-2", "review: ok", is_primary=False)
        )

        assert store.rows["art-2"]["is_primary_deliverable"] is False

    async def test_the_primary_projects_as_primary(self) -> None:
        store = _Store()
        projection = ArtifactListProjection(store)

        await projection.on_artifact_created(_created_event("art-1", "# Plan", is_primary=True))

        assert store.rows["art-1"]["is_primary_deliverable"] is True

    async def test_a_pre_v5_event_without_the_key_projects_as_primary(self) -> None:
        """Rows written before the flag existed cannot be back-filled, so
        the absent key must mean primary rather than secondary."""
        store = _Store()
        projection = ArtifactListProjection(store)

        await projection.on_artifact_created(
            {
                "artifact_id": "art-legacy",
                "workflow_id": "wf-1",
                "execution_id": "exec-1",
                "phase_id": "research",
                "artifact_type": "markdown",
                "title": "Research: legacy",
                "content": "legacy",
            }
        )

        assert store.rows["art-legacy"]["is_primary_deliverable"] is True


class TestTheAliasSurvivesTheWholeRestartPath:
    async def test_the_cold_path_injects_the_primary_after_a_restart(self) -> None:
        """The end-to-end assertion: collector order in, alias out.

        Every hop is real here -- aggregate, event, projection, read model,
        query service. Only the workspace is stood in for.
        """
        store = _Store()
        projection = ArtifactListProjection(store)

        # The collector writes the primary FIRST, then the rest.
        await projection.on_artifact_created(_created_event("art-1", "# Plan", is_primary=True))
        await projection.on_artifact_created(
            _created_event("art-2", "verdict: ok", is_primary=False)
        )

        # ...and the store hands them back newest-first.
        service = ArtifactQueryService(_ReadsBack(store))
        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"


class TestTheFlagIsReadStrictly:
    """Truthiness is not a decision.

    `bool("false")` is True and `bool(0)` is False, so coercing a row from a
    malformed or non-canonical writer silently promotes or demotes it. The
    failure mode is quiet and picks the wrong document either way.
    """

    def test_a_falsy_non_boolean_is_not_read_as_secondary(self) -> None:
        row: ProjectionRow = {
            "id": "art-1",
            "workflow_id": "wf-1",
            "execution_id": "exec-1",
            "session_id": None,
            "phase_id": "research",
            "artifact_type": "markdown",
            "name": "n",
            "created_at": None,
            "content": "x",
            "is_primary_deliverable": 0,
        }

        # `bool(0)` is False, so a coercing read would silently demote this
        # row out of the running for its phase's alias. A non-boolean value
        # carries no decision, so it falls back to the pre-#997 default
        # instead of being interpreted.
        assert ArtifactSummary.from_dict(dict(row)).is_primary_deliverable is True

    def test_a_real_false_survives(self) -> None:
        row: ProjectionRow = {
            "id": "art-2",
            "workflow_id": "wf-1",
            "execution_id": "exec-1",
            "session_id": None,
            "phase_id": "research",
            "artifact_type": "markdown",
            "name": "n",
            "created_at": None,
            "content": "x",
            "is_primary_deliverable": False,
        }

        assert ArtifactSummary.from_dict(dict(row)).is_primary_deliverable is False

    def test_an_absent_key_reads_as_primary(self) -> None:
        row: ProjectionRow = {
            "id": "art-3",
            "workflow_id": "wf-1",
            "execution_id": "exec-1",
            "session_id": None,
            "phase_id": "research",
            "artifact_type": "markdown",
            "name": "n",
            "created_at": None,
            "content": "x",
        }

        assert ArtifactSummary.from_dict(dict(row)).is_primary_deliverable is True
