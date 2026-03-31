"""Tests for ManageRepoHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain import HandlerResult
from syn_domain.contexts.organization.domain.aggregate_repo.RepoAggregate import (
    RepoAggregate,
)
from syn_domain.contexts.organization.domain.commands.AssignRepoToSystemCommand import (
    AssignRepoToSystemCommand,
)
from syn_domain.contexts.organization.domain.commands.RegisterRepoCommand import (
    RegisterRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.DeregisterRepoCommand import (
    DeregisterRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.UnassignRepoFromSystemCommand import (
    UnassignRepoFromSystemCommand,
)
from syn_domain.contexts.organization.domain.commands.UpdateRepoCommand import (
    UpdateRepoCommand,
)
from syn_domain.contexts.organization.slices.manage_repo.ManageRepoHandler import (
    ManageRepoHandler,
)


class InMemoryRepo:
    def __init__(self):
        self._items = {}

    async def save(self, aggregate):
        self._items[str(aggregate.id)] = aggregate

    async def get_by_id(self, id):
        return self._items.get(id)


async def _create_repo(repo, **overrides):
    agg = RepoAggregate()
    defaults = {
        "organization_id": "org-abc12345",
        "provider": "github",
        "full_name": "acme/backend-api",
        "owner": "acme",
        "created_by": "test-user",
    }
    defaults.update(overrides)
    agg.register(RegisterRepoCommand(**defaults))
    await repo.save(agg)
    return agg


@pytest.mark.unit
class TestManageRepoHandler:
    @pytest.mark.asyncio
    async def test_assign_to_system(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        result = await handler.assign_to_system(
            AssignRepoToSystemCommand(repo_id=agg.repo_id, system_id="sys-12345678")
        )
        assert result == HandlerResult(success=True)

        updated = await repo.get_by_id(agg.repo_id)
        assert updated.system_id == "sys-12345678"

    @pytest.mark.asyncio
    async def test_assign_already_assigned(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        await handler.assign_to_system(
            AssignRepoToSystemCommand(repo_id=agg.repo_id, system_id="sys-12345678")
        )
        result = await handler.assign_to_system(
            AssignRepoToSystemCommand(repo_id=agg.repo_id, system_id="sys-other")
        )
        assert result is not None
        assert result.success is False
        assert "already assigned" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unassign_from_system(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        await handler.assign_to_system(
            AssignRepoToSystemCommand(repo_id=agg.repo_id, system_id="sys-12345678")
        )
        result = await handler.unassign_from_system(
            UnassignRepoFromSystemCommand(repo_id=agg.repo_id)
        )
        assert result == HandlerResult(success=True)

        updated = await repo.get_by_id(agg.repo_id)
        assert updated.system_id == ""

    @pytest.mark.asyncio
    async def test_unassign_not_assigned(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        result = await handler.unassign_from_system(
            UnassignRepoFromSystemCommand(repo_id=agg.repo_id)
        )
        assert result is not None
        assert result.success is False
        assert "not assigned" in result.error.lower()

    @pytest.mark.asyncio
    async def test_assign_not_found(self) -> None:
        handler = ManageRepoHandler(repository=InMemoryRepo())
        result = await handler.assign_to_system(
            AssignRepoToSystemCommand(repo_id="nonexistent", system_id="sys-1")
        )
        assert result is None

    # --- Update tests ---

    @pytest.mark.asyncio
    async def test_update_default_branch(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        result = await handler.update(
            UpdateRepoCommand(repo_id=agg.repo_id, default_branch="develop")
        )
        assert result == HandlerResult(success=True)

        updated = await repo.get_by_id(agg.repo_id)
        assert updated.default_branch == "develop"

    @pytest.mark.asyncio
    async def test_update_is_private(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        result = await handler.update(
            UpdateRepoCommand(repo_id=agg.repo_id, is_private=True)
        )
        assert result == HandlerResult(success=True)

        updated = await repo.get_by_id(agg.repo_id)
        assert updated.is_private is True

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        result = await handler.update(
            UpdateRepoCommand(
                repo_id=agg.repo_id,
                default_branch="develop",
                is_private=True,
                installation_id="inst-99",
            )
        )
        assert result == HandlerResult(success=True)

        updated = await repo.get_by_id(agg.repo_id)
        assert updated.default_branch == "develop"
        assert updated.is_private is True
        assert updated.installation_id == "inst-99"

    @pytest.mark.asyncio
    async def test_update_deregistered_repo_fails(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        await handler.deregister(
            DeregisterRepoCommand(repo_id=agg.repo_id, deregistered_by="admin")
        )
        result = await handler.update(
            UpdateRepoCommand(repo_id=agg.repo_id, default_branch="develop")
        )
        assert result is not None
        assert result.success is False
        assert "deregistered" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_not_found(self) -> None:
        handler = ManageRepoHandler(repository=InMemoryRepo())
        result = await handler.update(
            UpdateRepoCommand(repo_id="nonexistent", default_branch="develop")
        )
        assert result is None

    # --- Deregister tests ---

    @pytest.mark.asyncio
    async def test_deregister_repo(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        result = await handler.deregister(
            DeregisterRepoCommand(repo_id=agg.repo_id, deregistered_by="admin")
        )
        assert result == HandlerResult(success=True)

        updated = await repo.get_by_id(agg.repo_id)
        assert updated.is_deregistered is True

    @pytest.mark.asyncio
    async def test_deregister_already_deregistered_fails(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        await handler.deregister(
            DeregisterRepoCommand(repo_id=agg.repo_id, deregistered_by="admin")
        )
        result = await handler.deregister(
            DeregisterRepoCommand(repo_id=agg.repo_id, deregistered_by="admin")
        )
        assert result is not None
        assert result.success is False
        assert "already deregistered" in result.error.lower()

    @pytest.mark.asyncio
    async def test_deregister_not_found(self) -> None:
        handler = ManageRepoHandler(repository=InMemoryRepo())
        result = await handler.deregister(
            DeregisterRepoCommand(repo_id="nonexistent", deregistered_by="admin")
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_assign_deregistered_repo_fails(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        await handler.deregister(
            DeregisterRepoCommand(repo_id=agg.repo_id, deregistered_by="admin")
        )
        result = await handler.assign_to_system(
            AssignRepoToSystemCommand(repo_id=agg.repo_id, system_id="sys-1")
        )
        assert result is not None
        assert result.success is False
        assert "deregistered" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unassign_deregistered_repo_fails(self) -> None:
        repo = InMemoryRepo()
        agg = await _create_repo(repo)
        handler = ManageRepoHandler(repository=repo)

        # First assign, then deregister, then try to unassign
        await handler.assign_to_system(
            AssignRepoToSystemCommand(repo_id=agg.repo_id, system_id="sys-1")
        )
        await handler.deregister(
            DeregisterRepoCommand(repo_id=agg.repo_id, deregistered_by="admin")
        )
        result = await handler.unassign_from_system(
            UnassignRepoFromSystemCommand(repo_id=agg.repo_id)
        )
        assert result is not None
        assert result.success is False
        assert "deregistered" in result.error.lower()
