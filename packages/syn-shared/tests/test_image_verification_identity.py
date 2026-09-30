<<<<<<< HEAD
"""The default cosign identity admits exactly one signer: AW's release branch.

agentic-workspace publishes and signs only from a push to its protected
``release`` branch (``release-images.yml``, ``SIGNER_IDENTITY``). A tag or a
GitHub release can be cut from any ref and would bypass the PR gate on
``release``, so a tag identity must NOT verify. These tests enumerate the
neighbouring SANs a looser pattern would admit, rather than one example.
=======
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
>>>>>>> origin/main
"""

from __future__ import annotations

import re

import pytest

from syn_shared.settings.image_verification import (
    AGENTIC_PRIMITIVES_IDENTITY_REGEXP,
    AGENTIC_WORKSPACE_IDENTITY_REGEXP,
<<<<<<< HEAD
    ImageVerificationSettings,
)

pytestmark = pytest.mark.unit

#: Copied verbatim from ``SIGNER_IDENTITY`` in AgentParadise/agentic-workspace
#: ``.github/workflows/release-images.yml``.
AW_RELEASE_SIGNER = (
    "https://github.com/AgentParadise/agentic-workspace"
    "/.github/workflows/release-images.yml@refs/heads/release"
)

_AW = "https://github.com/AgentParadise/agentic-workspace"
_AP = "https://github.com/AgentParadise/agentic-primitives"

REJECTED = [
    # Tags and releases can be created against any ref: not a trust root.
    f"{_AW}/.github/workflows/release-images.yml@refs/tags/v0.2.0",
    f"{_AW}/.github/workflows/release-images.yml@refs/tags/release",
    # Unreviewed or unprotected refs.
    f"{_AW}/.github/workflows/release-images.yml@refs/heads/main",
    f"{_AW}/.github/workflows/release-images.yml@refs/heads/release-candidate",
    f"{_AW}/.github/workflows/release-images.yml@refs/heads/feat/release",
    f"{_AW}/.github/workflows/release-images.yml@refs/pull/15/merge",
    # Another workflow in the same repository.
    f"{_AW}/.github/workflows/ci.yml@refs/heads/release",
    f"{_AW}/.github/workflows/release-images.yaml@refs/heads/release",
    # Look-alike repositories and owners.
    "https://github.com/AgentParadise/agentic-workspace-fork/.github/workflows/release-images.yml@refs/heads/release",
    "https://github.com/evil/agentic-workspace/.github/workflows/release-images.yml@refs/heads/release",
    # Anchoring: prefix and suffix smuggling.
    f"{AW_RELEASE_SIGNER}x",
    f"{AW_RELEASE_SIGNER}\n",
    f"x{AW_RELEASE_SIGNER}",
    # The former publisher is rollback-only, never the default.
    f"{_AP}/.github/workflows/build-workspace-images.yml@refs/heads/release",
    f"{_AP}/.github/workflows/build-workspace-images.yml@refs/heads/main",
]


def _matches(pattern: str, san: str) -> bool:
    # cosign (Go regexp) matches with MatchString; the pattern carries its own
    # anchors, so re.search is the faithful equivalent. \Z semantics: Python's
    # `$` also matches before a trailing newline, Go's does not, so a trailing
    # newline is asserted separately below instead of through `$`.
    return re.search(pattern, san) is not None


def test_the_default_is_the_workspace_identity() -> None:
    assert (
        ImageVerificationSettings(_env_file=None).certificate_identity_regexp
        == AGENTIC_WORKSPACE_IDENTITY_REGEXP
    )


def test_the_release_signer_verifies() -> None:
    assert _matches(AGENTIC_WORKSPACE_IDENTITY_REGEXP, AW_RELEASE_SIGNER)


@pytest.mark.parametrize("san", [s for s in REJECTED if not s.endswith("\n")])
def test_every_neighbouring_identity_is_rejected(san: str) -> None:
    assert not _matches(AGENTIC_WORKSPACE_IDENTITY_REGEXP, san), san


def test_trailing_newline_is_not_admitted_under_go_semantics() -> None:
    """Go's RE2 `$` without (?m) is end of text; emulate it with fullmatch."""
    san = f"{AW_RELEASE_SIGNER}\n"
    pattern = AGENTIC_WORKSPACE_IDENTITY_REGEXP.removeprefix("^").removesuffix("$")
    assert re.fullmatch(pattern, san) is None


def test_rollback_identity_still_admits_the_ap_release_build() -> None:
    """The rollback constant must keep verifying the AP digests it exists for."""
    assert _matches(
        AGENTIC_PRIMITIVES_IDENTITY_REGEXP,
        f"{_AP}/.github/workflows/build-workspace-images.yml@refs/heads/release",
    )
    assert not _matches(AGENTIC_PRIMITIVES_IDENTITY_REGEXP, AW_RELEASE_SIGNER)
=======
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
>>>>>>> origin/main
