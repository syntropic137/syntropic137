"""Tests for repo registration dedup via RepoClaimAggregate.

Uses lightweight in-memory repositories to verify the claim-then-register
flow without requiring the event store.
"""

from __future__ import annotations

from typing import Any

import pytest
from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts.organization.domain.commands.RegisterRepoCommand import (
    RegisterRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.ReleaseRepoClaimCommand import (
    ReleaseRepoClaimCommand,
)
from syn_domain.contexts.organization.slices.register_repo.RegisterRepoHandler import (
    RegisterRepoHandler,
)


class SimpleRepoRepository:
    """Minimal repo repository for testing."""

    def __init__(self) -> None:
        self._repos: dict[str, Any] = {}

    async def save(self, aggregate: Any) -> None:
        if aggregate.id:
            self._repos[str(aggregate.id)] = aggregate

    async def get_by_id(self, repo_id: str) -> Any:
        return self._repos.get(repo_id)


class SimpleClaimRepository:
    """Minimal claim repository with save_new() semantics."""

    def __init__(self) -> None:
        self._claims: dict[str, Any] = {}

    async def save(self, aggregate: Any) -> None:
        if aggregate.id:
            self._claims[str(aggregate.id)] = aggregate

    async def save_new(self, aggregate: Any) -> None:
        claim_id = str(aggregate.id) if aggregate.id else ""
        if claim_id and claim_id in self._claims:
            existing = self._claims[claim_id]
            if not existing.is_released:
                raise StreamAlreadyExistsError(
                    stream_name=f"RepoClaim-{claim_id}",
                    actual_version=1,
                )
        await self.save(aggregate)

    async def get_by_id(self, claim_id: str) -> Any:
        return self._claims.get(claim_id)


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
class TestRegisterRepoDedup:
    @pytest.mark.asyncio
    async def test_register_creates_claim_and_repo(self) -> None:
        repo_repo = SimpleRepoRepository()
        claim_repo = SimpleClaimRepository()
        handler = RegisterRepoHandler(repository=repo_repo, claim_repository=claim_repo)

        aggregate = await handler.handle(_make_command())

        assert aggregate.repo_id
        assert aggregate.full_name == "acme/backend-api"
        # Claim should exist
        assert len(claim_repo._claims) == 1

    @pytest.mark.asyncio
    async def test_duplicate_repo_raises_already_registered(self) -> None:
        repo_repo = SimpleRepoRepository()
        claim_repo = SimpleClaimRepository()
        handler = RegisterRepoHandler(repository=repo_repo, claim_repository=claim_repo)

        await handler.handle(_make_command())

        with pytest.raises(ValueError, match="already registered"):
            await handler.handle(_make_command())

    @pytest.mark.asyncio
    async def test_different_org_same_name_succeeds(self) -> None:
        repo_repo = SimpleRepoRepository()
        claim_repo = SimpleClaimRepository()
        handler = RegisterRepoHandler(repository=repo_repo, claim_repository=claim_repo)

        r1 = await handler.handle(_make_command(organization_id="org-1"))
        r2 = await handler.handle(_make_command(organization_id="org-2"))

        assert r1.repo_id != r2.repo_id
        assert len(claim_repo._claims) == 2

    @pytest.mark.asyncio
    async def test_different_provider_same_name_succeeds(self) -> None:
        repo_repo = SimpleRepoRepository()
        claim_repo = SimpleClaimRepository()
        handler = RegisterRepoHandler(repository=repo_repo, claim_repository=claim_repo)

        r1 = await handler.handle(_make_command(provider="github"))
        r2 = await handler.handle(_make_command(provider="gitea"))

        assert r1.repo_id != r2.repo_id

    @pytest.mark.asyncio
    async def test_register_after_deregister_succeeds(self) -> None:
        """Full lifecycle: register → release claim → re-register."""
        repo_repo = SimpleRepoRepository()
        claim_repo = SimpleClaimRepository()
        handler = RegisterRepoHandler(repository=repo_repo, claim_repository=claim_repo)

        # First registration
        r1 = await handler.handle(_make_command())

        # Simulate deregister by releasing the claim
        claim_id = next(iter(claim_repo._claims.keys()))
        existing_claim = claim_repo._claims[claim_id]
        existing_claim.release(ReleaseRepoClaimCommand(claim_id=claim_id, repo_id=r1.repo_id))
        await claim_repo.save(existing_claim)

        # Re-registration should succeed
        r2 = await handler.handle(_make_command())
        assert r2.repo_id != r1.repo_id
