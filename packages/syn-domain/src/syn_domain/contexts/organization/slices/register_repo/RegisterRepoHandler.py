"""Register Repo command handler.

Enforces repo uniqueness via the stream-per-unique-value pattern (ADR-021).
A lightweight RepoClaimAggregate is created first with a deterministic ID
derived from (org_id, provider, full_name). If the claim succeeds, the
RepoAggregate is created. If it fails, the repo is already registered.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts.organization.domain.aggregate_repo.RepoAggregate import (
    RepoAggregate,
)
from syn_domain.contexts.organization.domain.aggregate_repo_claim.claim_id import (
    compute_repo_claim_id,
)
from syn_domain.contexts.organization.domain.aggregate_repo_claim.RepoClaimAggregate import (
    RepoClaimAggregate,
)
from syn_domain.contexts.organization.domain.commands.ClaimRepoCommand import (
    ClaimRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.ReleaseRepoClaimCommand import (
    ReleaseRepoClaimCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.commands.RegisterRepoCommand import (
        RegisterRepoCommand,
    )

logger = logging.getLogger(__name__)


class RegisterRepoHandler:
    def __init__(self, repository: Any, claim_repository: Any) -> None:
        self._repository = repository
        self._claim_repository = claim_repository

    async def handle(self, command: RegisterRepoCommand) -> RepoAggregate:
        repo_id = command.aggregate_id or f"repo-{uuid4().hex[:8]}"
        claim_id = compute_repo_claim_id(
            command.organization_id, command.provider, command.full_name
        )

        # Attempt atomic claim via stream-per-unique-value pattern
        claim = RepoClaimAggregate()
        claim_command = ClaimRepoCommand(
            organization_id=command.organization_id,
            provider=command.provider,
            full_name=command.full_name,
            repo_id=repo_id,
            aggregate_id=claim_id,
        )
        claim.claim(claim_command)

        try:
            await self._claim_repository.save_new(claim)
        except StreamAlreadyExistsError:
            # Stream exists — check if released (re-registration after deregister)
            existing = await self._claim_repository.get_by_id(claim_id)
            if existing is not None and existing.is_released:
                # Re-claim after release
                reclaim_command = ClaimRepoCommand(
                    organization_id=command.organization_id,
                    provider=command.provider,
                    full_name=command.full_name,
                    repo_id=repo_id,
                    aggregate_id=claim_id,
                )
                existing.claim(reclaim_command)
                await self._claim_repository.save(existing)
            else:
                msg = (
                    f"Repository '{command.full_name}' is already registered "
                    f"in organization '{command.organization_id}'"
                )
                raise ValueError(msg) from None

        # Create the repo with the same pre-assigned ID used in the claim
        repo_command = replace(command, aggregate_id=repo_id)
        aggregate = RepoAggregate()
        try:
            aggregate.register(repo_command)
            await self._repository.save(aggregate)
        except Exception:
            # Compensate: release the claim so the name isn't permanently blocked
            logger.warning(
                "Repo save failed for '%s' — releasing claim %s",
                command.full_name,
                claim_id,
            )
            await self._release_claim(claim_id, repo_id)
            raise

        logger.info("Registered repo '%s' (%s)", aggregate.full_name, aggregate.repo_id)
        return aggregate

    async def _release_claim(self, claim_id: str, repo_id: str) -> None:
        """Best-effort compensating release after repo save failure."""
        try:
            existing = await self._claim_repository.get_by_id(claim_id)
            if existing is not None and not existing.is_released:
                existing.release(ReleaseRepoClaimCommand(claim_id=claim_id, repo_id=repo_id))
                await self._claim_repository.save(existing)
        except Exception:
            logger.error("Failed to release claim %s — may require manual cleanup", claim_id)
