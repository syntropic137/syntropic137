"""Tests for CreateSystemHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.commands.CreateSystemCommand import (
    CreateSystemCommand,
)
from syn_domain.contexts.organization.slices.create_system.CreateSystemHandler import (
    CreateSystemHandler,
)


class NullRepository:
    async def save(self, aggregate):
        pass

    async def get_by_id(self, id):
        return None


def _make_command(**overrides) -> CreateSystemCommand:
    defaults = {
        "organization_id": "org-abc12345",
        "name": "Backend Services",
        "description": "Core backend microservices",
        "created_by": "test-user",
    }
    defaults.update(overrides)
    return CreateSystemCommand(**defaults)


@pytest.mark.unit
class TestCreateSystemHandler:
    @pytest.mark.asyncio
    async def test_create_system(self) -> None:
        handler = CreateSystemHandler(repository=NullRepository())
        aggregate = await handler.handle(_make_command())

        assert aggregate.system_id.startswith("sys-")
        assert aggregate.name == "Backend Services"
        assert aggregate.organization_id == "org-abc12345"
        assert not aggregate.is_deleted

    @pytest.mark.asyncio
    async def test_create_multiple_systems(self) -> None:
        handler = CreateSystemHandler(repository=NullRepository())
        s1 = await handler.handle(_make_command(name="System 1"))
        s2 = await handler.handle(_make_command(name="System 2"))
        assert s1.system_id != s2.system_id

    def test_command_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name is required"):
            CreateSystemCommand(organization_id="org-1", name="", created_by="user")

    def test_command_rejects_empty_organization_id(self) -> None:
        with pytest.raises(ValueError, match="organization_id is required"):
            CreateSystemCommand(organization_id="", name="Test", created_by="user")
