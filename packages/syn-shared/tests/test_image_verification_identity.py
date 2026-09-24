"""The default cosign identity admits exactly one signer: AW's release branch.

agentic-workspace publishes and signs only from a push to its protected
``release`` branch (``release-images.yml``, ``SIGNER_IDENTITY``). A tag or a
GitHub release can be cut from any ref and would bypass the PR gate on
``release``, so a tag identity must NOT verify. These tests enumerate the
neighbouring SANs a looser pattern would admit, rather than one example.
"""

from __future__ import annotations

import re

import pytest

from syn_shared.settings.image_verification import (
    AGENTIC_PRIMITIVES_IDENTITY_REGEXP,
    AGENTIC_WORKSPACE_IDENTITY_REGEXP,
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
