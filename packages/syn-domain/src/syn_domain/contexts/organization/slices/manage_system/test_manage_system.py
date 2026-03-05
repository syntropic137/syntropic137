"""Tests for ManageSystemHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain import HandlerResult
from syn_domain.contexts.organization.domain.aggregate_system.SystemAggregate import (
    SystemAggregate,
)
from syn_domain.contexts.organization.domain.commands.CreateSystemCommand import (
    CreateSystemCommand,
)
from syn_domain.contexts.organization.domain.commands.DeleteSystemCommand import (
    DeleteSystemCommand,
)
from syn_domain.contexts.organization.domain.commands.UpdateSystemCommand import (
    UpdateSystemCommand,
)
from syn_domain.contexts.organization.slices.manage_system.ManageSystemHandler import (
    ManageSystemHandler,
)


class InMemoryRepo:
    def __init__(self):
        self._items = {}

    async def save(self, aggregate):
        self._items[str(aggregate.id)] = aggregate

    async def get_by_id(self, id):
        return self._items.get(id)


async def _create_system(repo, **overrides):
    agg = SystemAggregate()
    defaults = {
        "organization_id": "org-abc12345",
        "name": "Backend",
        "description": "Backend services",
        "created_by": "test-user",
    }
    defaults.update(overrides)
    agg.create(CreateSystemCommand(**defaults))
    await repo.save(agg)
    return agg


@pytest.mark.unit
class TestManageSystemHandler:
    @pytest.mark.asyncio
    async def test_update_name(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_system(repo)
        handler = ManageSystemHandler(repository=repo)

        result = await handler.update(UpdateSystemCommand(system_id=agg.system_id, name="New Name"))
        assert result == HandlerResult(success=True)

        updated = await repo.get_by_id(agg.system_id)
        assert updated.name == "New Name"

    @pytest.mark.asyncio
    async def test_update_not_found(self) -> None:
        handler = ManageSystemHandler(repository=InMemoryRepo())
        result = await handler.update(UpdateSystemCommand(system_id="nonexistent", name="X"))
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_system(repo)
        handler = ManageSystemHandler(repository=repo)

        result = await handler.delete(
            DeleteSystemCommand(system_id=agg.system_id, deleted_by="test")
        )
        assert result == HandlerResult(success=True)

        deleted = await repo.get_by_id(agg.system_id)
        assert deleted.is_deleted

    @pytest.mark.asyncio
    async def test_delete_already_deleted(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_system(repo)
        handler = ManageSystemHandler(repository=repo)

        await handler.delete(DeleteSystemCommand(system_id=agg.system_id, deleted_by="test"))
        result = await handler.delete(
            DeleteSystemCommand(system_id=agg.system_id, deleted_by="test")
        )
        assert result is not None
        assert result.success is False
        assert "already deleted" in result.error.lower()
