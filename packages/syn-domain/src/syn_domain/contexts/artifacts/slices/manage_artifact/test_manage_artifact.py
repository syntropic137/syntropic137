"""Tests for ManageArtifactHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.artifacts._shared.value_objects import ArtifactType
from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
    ArtifactAggregate,
)
from syn_domain.contexts.artifacts.domain.commands.CreateArtifactCommand import (
    CreateArtifactCommand,
)
from syn_domain.contexts.artifacts.domain.commands.DeleteArtifactCommand import (
    DeleteArtifactCommand,
)
from syn_domain.contexts.artifacts.domain.commands.UpdateArtifactCommand import (
    UpdateArtifactCommand,
)
from syn_domain.contexts.artifacts.slices.manage_artifact.ManageArtifactHandler import (
    ManageArtifactHandler,
)


class InMemoryRepo:
    def __init__(self):
        self._items = {}

    async def save(self, aggregate):
        self._items[str(aggregate.id)] = aggregate

    async def get_by_id(self, id):
        return self._items.get(id)


async def _create_artifact(repo, **overrides):
    agg = ArtifactAggregate()
    defaults = {
        "aggregate_id": "art-test-001",
        "workflow_id": "wf-abc",
        "phase_id": "phase-1",
        "artifact_type": ArtifactType.CODE,
        "content": "print('hello')",
        "title": "Test Artifact",
    }
    defaults.update(overrides)
    agg._handle_command(CreateArtifactCommand(**defaults))
    await repo.save(agg)
    return agg


@pytest.mark.unit
class TestManageArtifactHandler:
    @pytest.mark.asyncio
    async def test_update_title(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_artifact(repo)
        handler = ManageArtifactHandler(repository=repo)

        await handler.update(UpdateArtifactCommand(aggregate_id=str(agg.id), title="New Title"))

        updated = await repo.get_by_id(str(agg.id))
        assert updated.title == "New Title"

    @pytest.mark.asyncio
    async def test_update_metadata(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_artifact(repo)
        handler = ManageArtifactHandler(repository=repo)

        await handler.update(
            UpdateArtifactCommand(
                aggregate_id=str(agg.id),
                metadata={"language": "python", "lines": 42},
            )
        )

        updated = await repo.get_by_id(str(agg.id))
        assert updated._metadata == {"language": "python", "lines": 42}

    @pytest.mark.asyncio
    async def test_update_is_primary_deliverable(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_artifact(repo)
        handler = ManageArtifactHandler(repository=repo)

        await handler.update(
            UpdateArtifactCommand(aggregate_id=str(agg.id), is_primary_deliverable=False)
        )

        updated = await repo.get_by_id(str(agg.id))
        assert updated.is_primary_deliverable is False

    @pytest.mark.asyncio
    async def test_update_deleted_artifact_fails(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_artifact(repo)
        handler = ManageArtifactHandler(repository=repo)

        await handler.delete(DeleteArtifactCommand(aggregate_id=str(agg.id), deleted_by="admin"))

        with pytest.raises(ValueError, match="deleted"):
            await handler.update(UpdateArtifactCommand(aggregate_id=str(agg.id), title="New Title"))

    @pytest.mark.asyncio
    async def test_update_not_found(self) -> None:
        handler = ManageArtifactHandler(repository=InMemoryRepo())
        with pytest.raises(KeyError):
            await handler.update(
                UpdateArtifactCommand(aggregate_id="nonexistent", title="New Title")
            )

    @pytest.mark.asyncio
    async def test_delete_artifact(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_artifact(repo)
        handler = ManageArtifactHandler(repository=repo)

        result = await handler.delete(
            DeleteArtifactCommand(aggregate_id=str(agg.id), deleted_by="admin")
        )
        assert result is True

        updated = await repo.get_by_id(str(agg.id))
        assert updated.is_deleted is True

    @pytest.mark.asyncio
    async def test_delete_already_deleted_fails(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_artifact(repo)
        handler = ManageArtifactHandler(repository=repo)

        await handler.delete(DeleteArtifactCommand(aggregate_id=str(agg.id), deleted_by="admin"))

        with pytest.raises(ValueError, match="already deleted"):
            await handler.delete(
                DeleteArtifactCommand(aggregate_id=str(agg.id), deleted_by="admin")
            )

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        handler = ManageArtifactHandler(repository=InMemoryRepo())
        with pytest.raises(KeyError):
            await handler.delete(
                DeleteArtifactCommand(aggregate_id="nonexistent", deleted_by="admin")
            )
