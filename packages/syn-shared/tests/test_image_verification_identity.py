"""The default signing identity must admit exactly ONE publisher.

Workspace image publishing MOVED from agentic-primitives to agentic-workspace.
The default admitted both for the duration of that cutover; every pin now
comes from agentic-workspace, so the retired publisher is no longer trusted by
default. Trusting a signer nothing needs is the drift this constraint exists
to prevent.

Widening an identity constraint is the dangerous direction. These tests pin the
WHOLE admitted set: the one real publisher identity matches, and a list of
near-miss identities does not. The near misses are the ones a hand-written
identity actually gets wrong - a missing anchor makes a good SAN match as a
substring of a longer one, and an unescaped dot makes a lookalike host match.
Asserting only that the good identity passes would leave that class open.

The retired agentic-primitives identities are in the REJECTED list on purpose.
They were admitted during the cutover, so a regression that re-admits them
would otherwise look like nothing.
"""

from __future__ import annotations

import re

import pytest

from syn_shared.settings.image_verification import (
    AGENTIC_PRIMITIVES_IDENTITY_REGEXP,
    AGENTIC_WORKSPACE_IDENTITY_REGEXP,
    WORKSPACE_IMAGE_IDENTITY_REGEXP,
    ImageVerificationSettings,
)

_PRIMITIVES_WORKFLOW = (
    "https://github.com/AgentParadise/agentic-primitives"
    "/.github/workflows/build-workspace-images.yml"
)
_WORKSPACE_WORKFLOW = (
    "https://github.com/AgentParadise/agentic-workspace/.github/workflows/release-images.yml"
)

ADMITTED = [
    f"{_WORKSPACE_WORKFLOW}@refs/heads/release",
]

REJECTED = [
    # The RETIRED publisher. Admitted during the cutover, rejected now. An
    # operator overriding SYN_WORKSPACE_DOCKER_IMAGE to an old digest must set
    # the identity explicitly rather than have it trusted by default.
    f"{_PRIMITIVES_WORKFLOW}@refs/heads/main",
    f"{_PRIMITIVES_WORKFLOW}@refs/heads/release",
    # agentic-workspace publishes ONLY from the protected release branch.
    f"{_WORKSPACE_WORKFLOW}@refs/heads/main",
    f"{_WORKSPACE_WORKFLOW}@refs/tags/v1.0.0",
    f"{_WORKSPACE_WORKFLOW}@refs/pull/1/merge",
    # A different workflow in the right repository.
    "https://github.com/AgentParadise/agentic-workspace"
    "/.github/workflows/ci.yml@refs/heads/release",
    # The right workflow path in the wrong repository.
    "https://github.com/AgentParadise/agentic-workspace-legacy"
    "/.github/workflows/release-images.yml@refs/heads/release",
    "https://github.com/attacker/agentic-workspace"
    "/.github/workflows/release-images.yml@refs/heads/release",
    # Anchor checks: a good identity embedded in a longer SAN must not match.
    f"https://evil.example.com/?x={_WORKSPACE_WORKFLOW}@refs/heads/release",
    f"{_WORKSPACE_WORKFLOW}@refs/heads/release.evil.example.com",
    # Host confusion: the dots in the pattern are escaped, so this must fail.
    "https://githubXcom/AgentParadise/agentic-workspace"
    "/.github/workflows/release-images.yml@refs/heads/release",
]


@pytest.mark.unit
@pytest.mark.parametrize("identity", ADMITTED)
def test_admitted_publisher_identities_match(identity: str) -> None:
    assert re.match(WORKSPACE_IMAGE_IDENTITY_REGEXP, identity) is not None


@pytest.mark.unit
@pytest.mark.parametrize("identity", REJECTED)
def test_rejected_identities_do_not_match(identity: str) -> None:
    assert re.match(WORKSPACE_IMAGE_IDENTITY_REGEXP, identity) is None


@pytest.mark.unit
def test_fullmatch_and_search_agree() -> None:
    """A substring match must not be possible for any admitted identity.

    ``cosign`` applies the pattern with Go's regexp, which is unanchored by
    default, so a pattern that only works under ``re.match`` would be a real
    hole. Every alternative therefore carries its own ``^``/``$``, and
    ``re.search`` must reject the same things ``re.match`` rejects.
    """
    for identity in REJECTED:
        assert re.search(WORKSPACE_IMAGE_IDENTITY_REGEXP, identity) is None
    for identity in ADMITTED:
        assert re.search(WORKSPACE_IMAGE_IDENTITY_REGEXP, identity) is not None


@pytest.mark.unit
def test_default_setting_is_the_new_publisher_only() -> None:
    """The shipped default must be agentic-workspace, and only it."""
    settings = ImageVerificationSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    assert settings.certificate_identity_regexp == WORKSPACE_IMAGE_IDENTITY_REGEXP
    assert WORKSPACE_IMAGE_IDENTITY_REGEXP == AGENTIC_WORKSPACE_IDENTITY_REGEXP
    assert "agentic-primitives" not in WORKSPACE_IMAGE_IDENTITY_REGEXP, (
        "the retired publisher is still trusted by default"
    )


@pytest.mark.unit
def test_the_retired_identity_is_still_exported() -> None:
    """Not trusted by default, but still SPELLED here.

    An operator overriding SYN_WORKSPACE_DOCKER_IMAGE to an old
    agentic-primitives digest needs its signer's identity. Deleting the
    constant would leave them writing one by hand, which is how a wrong
    identity constraint gets authored.
    """
    assert "agentic-primitives" in AGENTIC_PRIMITIVES_IDENTITY_REGEXP
    assert re.match(
        AGENTIC_PRIMITIVES_IDENTITY_REGEXP, f"{_PRIMITIVES_WORKFLOW}@refs/heads/release"
    )


@pytest.mark.unit
def test_verification_is_on_by_default() -> None:
    """Widening the identity must not have relaxed the fail-closed default."""
    settings = ImageVerificationSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    assert settings.enabled is True
    assert settings.allow_local_images is False
