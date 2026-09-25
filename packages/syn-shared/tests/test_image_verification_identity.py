"""The default signing identity must admit exactly two publishers.

Workspace image publishing is moving from agentic-primitives to
agentic-workspace. During the cutover the default identity constraint admits
both, because a running deployment pins digests built by the old publisher
while the pins move in a separate change.

Widening an identity constraint is the dangerous direction. These tests pin the
whole admitted set: both real publisher identities match, and a list of
near-miss identities does not. The near misses are the ones an alternation
built by string concatenation actually gets wrong - a missing anchor makes a
SAN match as a substring, and a stray group makes a different repository or
workflow match. Asserting only that the two good identities pass would leave
that entire class open.
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
    "https://github.com/AgentParadise/agentic-workspace"
    "/.github/workflows/release-images.yml"
)

ADMITTED = [
    f"{_PRIMITIVES_WORKFLOW}@refs/heads/main",
    f"{_PRIMITIVES_WORKFLOW}@refs/heads/release",
    f"{_WORKSPACE_WORKFLOW}@refs/heads/release",
]

REJECTED = [
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
def test_default_setting_is_the_combined_identity() -> None:
    """The shipped default must be the alternation, not one publisher."""
    settings = ImageVerificationSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    assert settings.certificate_identity_regexp == WORKSPACE_IMAGE_IDENTITY_REGEXP
    assert AGENTIC_PRIMITIVES_IDENTITY_REGEXP in WORKSPACE_IMAGE_IDENTITY_REGEXP
    assert AGENTIC_WORKSPACE_IDENTITY_REGEXP in WORKSPACE_IMAGE_IDENTITY_REGEXP


@pytest.mark.unit
def test_verification_is_on_by_default() -> None:
    """Widening the identity must not have relaxed the fail-closed default."""
    settings = ImageVerificationSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    assert settings.enabled is True
    assert settings.allow_local_images is False
