"""GetArtifactHandler: a read by id that does not wait for the read model (#1570).

"Behind" here is literal: the projection is a real ``ArtifactListProjection``
that has been handed none of the events the aggregate saved, and each test
asserts its row is absent before reading, so nothing passes by finding it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.artifacts._shared.value_objects import ArtifactType, ContentType
from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
    ArtifactAggregate,
)
from syn_domain.contexts.artifacts.domain.commands.CreateArtifactCommand import (
    CreateArtifactCommand,
)
from syn_domain.contexts.artifacts.domain.commands.DeleteArtifactCommand import (
    DeleteArtifactCommand,
)
from syn_domain.contexts.artifacts.slices.get_artifact import GetArtifactHandler
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

ARTIFACT_ID = "art-1570"
#: The key MinIO writes for an execution-scoped upload. The artifact id alone
#: builds ``artifacts/art-1570.md``, which is not where the bytes are (#1652).
STORAGE_URI = "s3://syn-artifacts/artifacts/wf-1570/exec-1570/art-1570.md"


class _Store:
    """A projection store, keyed the way every real one is."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, object]] = {}

    async def save(self, namespace: str, key: str, data: dict[str, object]) -> None:
        self.rows[(namespace, key)] = data

    async def get(self, namespace: str, key: str) -> dict[str, object] | None:
        return self.rows.get((namespace, key))


class _Repo:
    """The event store, as the handler sees it: aggregates rebuilt from their events."""

    def __init__(self) -> None:
        self._envelopes: dict[str, list[EventEnvelope[DomainEvent]]] = {}

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self._envelopes.setdefault(str(aggregate.id), []).extend(
            aggregate.get_uncommitted_events()
        )
        aggregate.mark_events_as_committed()

    async def get_by_id(self, aggregate_id: str) -> ArtifactAggregate | None:
        envelopes = self._envelopes.get(aggregate_id)
        if not envelopes:
            return None
        aggregate = ArtifactAggregate()
        aggregate.rehydrate(envelopes)
        return aggregate

    def events(self, aggregate_id: str) -> list[DomainEvent]:
        return [envelope.event for envelope in self._envelopes[aggregate_id]]


async def _created(repo: _Repo) -> ArtifactAggregate:
    aggregate = ArtifactAggregate()
    aggregate._handle_command(  # noqa: SLF001
        CreateArtifactCommand(
            aggregate_id=ARTIFACT_ID,
            workflow_id="wf-1570",
            execution_id="exec-1570",
            session_id="sess-1570",
            phase_id="research",
            artifact_type=ArtifactType.RESEARCH_SUMMARY,
            content_type=ContentType.TEXT_MARKDOWN,
            content="# Findings\n\n34,621 characters of them, in production.",
            title="Research findings",
            source_path="research/findings.md",
            agent_provider="claude",
            agent_model="claude-opus-5-5",
            storage_uri=STORAGE_URI,
            is_primary_deliverable=False,
        )
    )
    await repo.save(aggregate)
    return aggregate


@pytest.fixture
def projection() -> ArtifactListProjection:
    return ArtifactListProjection(_Store())


async def test_an_artifact_the_projection_has_not_seen_is_found_with_its_storage_key(
    projection: ArtifactListProjection,
) -> None:
    repo = _Repo()
    await _created(repo)
    assert await projection.get_by_id(ARTIFACT_ID) is None

    found = await GetArtifactHandler(projection, repo).handle(ARTIFACT_ID)

    assert found is not None
    assert found.id == ARTIFACT_ID
    assert found.storage_uri == STORAGE_URI


async def test_the_fallback_is_the_row_the_projection_writes_once_it_catches_up(
    projection: ArtifactListProjection,
) -> None:
    """Every field, not just the key: a reader cannot tell which path answered."""
    repo = _Repo()
    await _created(repo)
    from_aggregate = await GetArtifactHandler(projection, repo).handle(ARTIFACT_ID)

    for event in repo.events(ARTIFACT_ID):
        await projection.on_artifact_created(event.model_dump())
    from_projection = await projection.get_by_id(ARTIFACT_ID)

    assert from_aggregate is not None
    assert from_projection is not None
    assert from_aggregate.to_dict() == from_projection.to_dict()


async def test_a_projection_row_answers_without_loading_the_aggregate(
    projection: ArtifactListProjection,
) -> None:
    repo = _Repo()
    await _created(repo)
    for event in repo.events(ARTIFACT_ID):
        await projection.on_artifact_created(event.model_dump())

    class _Unreachable(_Repo):
        async def get_by_id(self, aggregate_id: str) -> ArtifactAggregate | None:
            raise AssertionError(f"loaded {aggregate_id} although the read model had it")

    found = await GetArtifactHandler(projection, _Unreachable()).handle(ARTIFACT_ID)
    assert found is not None
    assert found.storage_uri == STORAGE_URI


async def test_a_deleted_artifact_is_not_found_while_the_projection_lags(
    projection: ArtifactListProjection,
) -> None:
    repo = _Repo()
    aggregate = await _created(repo)
    aggregate._handle_command(DeleteArtifactCommand(aggregate_id=ARTIFACT_ID))  # noqa: SLF001
    await repo.save(aggregate)

    assert await GetArtifactHandler(projection, repo).handle(ARTIFACT_ID) is None


async def test_an_artifact_that_was_never_created_is_not_found(
    projection: ArtifactListProjection,
) -> None:
    assert await GetArtifactHandler(projection, _Repo()).handle("art-never") is None
