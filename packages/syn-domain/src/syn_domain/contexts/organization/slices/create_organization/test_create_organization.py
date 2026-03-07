"""Tests for CreateOrganizationHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.commands.CreateOrganizationCommand import (
    CreateOrganizationCommand,
)
from syn_domain.contexts.organization.slices.create_organization.CreateOrganizationHandler import (
    CreateOrganizationHandler,
)


class NullRepository:
    """No-op repository for unit tests."""

    async def save(self, aggregate):
        pass

    async def get_by_id(self, id):
        return None


def _make_command(**overrides) -> CreateOrganizationCommand:
    defaults = {
        "name": "Acme Corp",
        "slug": "acme-corp",
        "created_by": "test-user",
    }
    defaults.update(overrides)
    return CreateOrganizationCommand(**defaults)


@pytest.mark.unit
class TestCreateOrganizationHandler:
    @pytest.mark.asyncio
    async def test_create_organization(self) -> None:
        handler = CreateOrganizationHandler(repository=NullRepository())
        aggregate = await handler.handle(_make_command())

        assert aggregate.organization_id.startswith("org-")
        assert aggregate.name == "Acme Corp"
        assert aggregate.slug == "acme-corp"
        assert not aggregate.is_deleted

    @pytest.mark.asyncio
    async def test_create_multiple_organizations(self) -> None:
        handler = CreateOrganizationHandler(repository=NullRepository())
        o1 = await handler.handle(_make_command(name="Org 1", slug="org-1"))
        o2 = await handler.handle(_make_command(name="Org 2", slug="org-2"))
        assert o1.organization_id != o2.organization_id

    def test_command_validation_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name is required"):
            CreateOrganizationCommand(name="", slug="test", created_by="user")

    def test_command_validation_rejects_empty_slug(self) -> None:
        with pytest.raises(ValueError, match="slug is required"):
            CreateOrganizationCommand(name="Test", slug="", created_by="user")
