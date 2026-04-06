"""Tests for RepoClaimAggregate and claim_id utility."""

from __future__ import annotations

import pytest

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


def _make_claim_command(**overrides) -> ClaimRepoCommand:
    claim_id = compute_repo_claim_id(
        overrides.get("organization_id", "org-1"),
        overrides.get("provider", "github"),
        overrides.get("full_name", "acme/repo"),
    )
    defaults = {
        "organization_id": "org-1",
        "provider": "github",
        "full_name": "acme/repo",
        "repo_id": "repo-abc123",
        "aggregate_id": claim_id,
    }
    defaults.update(overrides)
    if "aggregate_id" not in overrides:
        defaults["aggregate_id"] = compute_repo_claim_id(
            defaults["organization_id"], defaults["provider"], defaults["full_name"]
        )
    return ClaimRepoCommand(**defaults)


@pytest.mark.unit
class TestRepoClaimAggregate:
    def test_claim_creates_event(self) -> None:
        claim = RepoClaimAggregate()
        claim.claim(_make_claim_command())

        assert claim.organization_id == "org-1"
        assert claim.provider == "github"
        assert claim.full_name == "acme/repo"
        assert claim.repo_id == "repo-abc123"
        assert not claim.is_released

    def test_double_claim_raises(self) -> None:
        claim = RepoClaimAggregate()
        claim.claim(_make_claim_command())

        with pytest.raises(ValueError, match="already claimed"):
            claim.claim(_make_claim_command(repo_id="repo-other"))

    def test_release_creates_event(self) -> None:
        claim = RepoClaimAggregate()
        claim.claim(_make_claim_command())

        release = ReleaseRepoClaimCommand(
            claim_id=str(claim.id),
            repo_id=claim.repo_id,
        )
        claim.release(release)

        assert claim.is_released

    def test_release_then_reclaim(self) -> None:
        claim = RepoClaimAggregate()
        claim.claim(_make_claim_command())

        release = ReleaseRepoClaimCommand(
            claim_id=str(claim.id),
            repo_id=claim.repo_id,
        )
        claim.release(release)
        assert claim.is_released

        # Re-claim with a new repo ID
        claim.claim(_make_claim_command(repo_id="repo-new123"))
        assert not claim.is_released
        assert claim.repo_id == "repo-new123"

    def test_release_nonexistent_raises(self) -> None:
        claim = RepoClaimAggregate()
        with pytest.raises(ValueError, match="does not exist"):
            claim.release(ReleaseRepoClaimCommand(claim_id="fake", repo_id="repo-1"))

    def test_double_release_raises(self) -> None:
        claim = RepoClaimAggregate()
        claim.claim(_make_claim_command())

        release = ReleaseRepoClaimCommand(claim_id=str(claim.id), repo_id=claim.repo_id)
        claim.release(release)

        with pytest.raises(ValueError, match="already released"):
            claim.release(release)


@pytest.mark.unit
class TestClaimId:
    def test_claim_id_deterministic(self) -> None:
        id1 = compute_repo_claim_id("org-1", "github", "acme/repo")
        id2 = compute_repo_claim_id("org-1", "github", "acme/repo")
        assert id1 == id2

    def test_claim_id_differs_for_different_inputs(self) -> None:
        id1 = compute_repo_claim_id("org-1", "github", "acme/repo")
        id2 = compute_repo_claim_id("org-2", "github", "acme/repo")
        id3 = compute_repo_claim_id("org-1", "gitea", "acme/repo")
        id4 = compute_repo_claim_id("org-1", "github", "acme/other")
        assert len({id1, id2, id3, id4}) == 4

    def test_claim_id_has_prefix(self) -> None:
        claim_id = compute_repo_claim_id("org-1", "github", "acme/repo")
        assert claim_id.startswith("rc-")
        assert len(claim_id) == 19  # "rc-" + 16 hex chars
