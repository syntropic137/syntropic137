"""Tests for ManageOrganizationHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.aggregate_organization.OrganizationAggregate import (
    OrganizationAggregate,
)
from syn_domain.contexts.organization.domain.commands.CreateOrganizationCommand import (
    CreateOrganizationCommand,
)
from syn_domain.contexts.organization.domain.commands.DeleteOrganizationCommand import (
    DeleteOrganizationCommand,
)
from syn_domain.contexts.organization.domain.commands.UpdateOrganizationCommand import (
    UpdateOrganizationCommand,
)
from syn_domain.contexts.organization.slices.manage_organization.ManageOrganizationHandler import (
    ManageOrganizationHandler,
)


class InMemoryRepo:
    def __init__(self):
        self._items = {}

    async def save(self, aggregate):
        self._items[str(aggregate.id)] = aggregate

    async def get_by_id(self, id):
        return self._items.get(id)


async def _create_org(repo, **overrides):
    agg = OrganizationAggregate()
    defaults = {"name": "Acme Corp", "slug": "acme-corp", "created_by": "test-user"}
    defaults.update(overrides)
    agg.create(CreateOrganizationCommand(**defaults))
    await repo.save(agg)
    return agg


@pytest.mark.unit
class TestManageOrganizationHandler:
    @pytest.mark.asyncio
    async def test_update_name(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_org(repo)
        handler = ManageOrganizationHandler(repository=repo)

        result = await handler.update(
            UpdateOrganizationCommand(organization_id=agg.organization_id, name="New Name")
        )
        assert result is True

        updated = await repo.get_by_id(agg.organization_id)
        assert updated.name == "New Name"

    @pytest.mark.asyncio
    async def test_update_not_found(self) -> None:
        handler = ManageOrganizationHandler(repository=InMemoryRepo())
        result = await handler.update(
            UpdateOrganizationCommand(organization_id="nonexistent", name="X")
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_org(repo)
        handler = ManageOrganizationHandler(repository=repo)

        result = await handler.delete(
            DeleteOrganizationCommand(organization_id=agg.organization_id, deleted_by="test")
        )
        assert result is True

        deleted = await repo.get_by_id(agg.organization_id)
        assert deleted.is_deleted

    @pytest.mark.asyncio
    async def test_delete_already_deleted(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_org(repo)
        handler = ManageOrganizationHandler(repository=repo)

        await handler.delete(
            DeleteOrganizationCommand(organization_id=agg.organization_id, deleted_by="test")
        )
        result = await handler.delete(
            DeleteOrganizationCommand(organization_id=agg.organization_id, deleted_by="test")
        )
        assert result is None
