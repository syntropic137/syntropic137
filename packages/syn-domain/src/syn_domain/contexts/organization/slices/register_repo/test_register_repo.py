"""Tests for RegisterRepoHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.commands.RegisterRepoCommand import (
    RegisterRepoCommand,
)
from syn_domain.contexts.organization.slices.register_repo.RegisterRepoHandler import (
    RegisterRepoHandler,
)


class NullRepository:
    async def save(self, aggregate):
        pass

    async def get_by_id(self, id):
        return None


def _make_command(**overrides) -> RegisterRepoCommand:
    defaults = {
        "organization_id": "org-abc12345",
        "provider": "github",
        "full_name": "acme/backend-api",
        "owner": "acme",
        "default_branch": "main",
        "created_by": "test-user",
    }
    defaults.update(overrides)
    return RegisterRepoCommand(**defaults)


@pytest.mark.unit
class TestRegisterRepoHandler:
    @pytest.mark.asyncio
    async def test_register_repo(self) -> None:
        handler = RegisterRepoHandler(repository=NullRepository())
        aggregate = await handler.handle(_make_command())

        assert aggregate.repo_id.startswith("repo-")
        assert aggregate.full_name == "acme/backend-api"
        assert aggregate.organization_id == "org-abc12345"
        assert aggregate.provider == "github"
        assert aggregate.system_id == ""

    @pytest.mark.asyncio
    async def test_register_multiple_repos(self) -> None:
        handler = RegisterRepoHandler(repository=NullRepository())
        r1 = await handler.handle(_make_command(full_name="acme/repo-1"))
        r2 = await handler.handle(_make_command(full_name="acme/repo-2"))
        assert r1.repo_id != r2.repo_id

    def test_command_rejects_empty_full_name(self) -> None:
        with pytest.raises(ValueError, match="full_name is required"):
            RegisterRepoCommand(organization_id="org-1", provider="github", full_name="")

    def test_command_rejects_invalid_provider(self) -> None:
        with pytest.raises(ValueError, match="provider must be"):
            RegisterRepoCommand(
                organization_id="org-1", provider="bitbucket", full_name="acme/repo"
            )
