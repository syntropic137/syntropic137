"""Image names must match what agentic-workspace actually publishes.

A workspace image name is a cross-repo contract: agentic-workspace's release
workflow (``.github/workflows/release-images.yml``) declares, per publishing
job, ``PROVIDER: <provider>`` and ``IMAGE: ghcr.io/agentparadise/<name>``, and
this repo has to reference the same ``<name>``. Deriving it from a pattern is
the tempting move and it is wrong - claude-cli publishes as
``agentic-workspace-claude``, because ``agentic-workspace-claude-cli`` is the
GHCR package agentic-primitives already owns. The manifest ``image.tag`` is only
the LOCAL build tag and does not decide the published name.

Getting it wrong fails at workspace provision time, in a pull or signature
error far from the constant that caused it. These tests read the vendored
workflow and compare, so a rename upstream fails here instead.

Skipped when the submodule is not checked out, or when the vendored commit
predates the release-branch pipeline (no PROVIDER/IMAGE pairs), so a shallow
clone does not fail the suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syn_shared.settings.workspace_images import (
    AW_RELEASE_DIGEST_PENDING,
    DEFAULT_WORKSPACE_IMAGE,
    GHCR_OWNER,
    GHCR_REGISTRY,
    PINNED_DIGESTS,
    WorkspaceImageProvider,
    workspace_image_name,
    workspace_image_ref,
)

pytestmark = pytest.mark.unit

_RELEASE_WORKFLOW = (
    Path(__file__).resolve().parents[3]
    / "lib"
    / "agentic-workspace"
    / ".github"
    / "workflows"
    / "release-images.yml"
)

_PAIR = re.compile(
    r"^\s+PROVIDER:\s*([\w-]+)\s*\n\s+IMAGE:\s*"
    + re.escape(f"{GHCR_REGISTRY}/{GHCR_OWNER}/")
    + r"([\w.-]+)\s*$",
    re.MULTILINE,
)


def _published_names() -> dict[str, str]:
    if not _RELEASE_WORKFLOW.is_file():
        pytest.skip("agentic-workspace submodule not checked out")
    pairs = dict(_PAIR.findall(_RELEASE_WORKFLOW.read_text()))
    if not pairs:
        pytest.skip(
            "vendored agentic-workspace predates the release-branch pipeline "
            "(no PROVIDER/IMAGE pairs in release-images.yml)"
        )
    return pairs


@pytest.mark.parametrize("provider", list(WorkspaceImageProvider))
def test_image_name_matches_the_release_workflow(provider: WorkspaceImageProvider) -> None:
    published = _published_names()
    assert provider.value in published, (
        f"agentic-workspace's release workflow does not publish {provider.value!r}; "
        f"it publishes {sorted(published)}. A pinned provider nobody publishes cannot "
        f"be bumped."
    )
    assert workspace_image_name(provider) == published[provider.value], (
        f"{provider.value}: this repo references {workspace_image_name(provider)!r} but "
        f"agentic-workspace publishes {published[provider.value]!r}. Add or correct an "
        f"entry in IMAGE_NAME_OVERRIDES - do NOT change the derivation pattern, other "
        f"providers depend on it."
    )


class TestClaudeIsTheKnownException:
    """Pin the specific case that motivated the override map."""

    def test_claude_does_not_use_the_derived_name(self) -> None:
        name = workspace_image_name(WorkspaceImageProvider.CLAUDE_CLI)
        assert name == "agentic-workspace-claude"
        # AP's package: pulling it would run an image signed by another identity.
        assert name != "agentic-workspace-claude-cli"

    def test_claude_ref_is_fully_qualified(self) -> None:
        ref = workspace_image_ref(WorkspaceImageProvider.CLAUDE_CLI)
        assert ref.split("@")[0] == "ghcr.io/agentparadise/agentic-workspace-claude"
        assert "@sha256:" in ref


class TestDerivedProviders:
    """Providers without an override use ``agentic-workspace-<provider>``."""

    def test_omni_derives(self) -> None:
        ref = workspace_image_ref(WorkspaceImageProvider.OMNI_AGENT)
        assert ref.split("@")[0] == "ghcr.io/agentparadise/agentic-workspace-omni-agent"
        # The AP name: a different publisher and signing identity.
        assert "omni-agent-workspace" not in ref

    def test_buildfloor_derives_and_is_the_default(self) -> None:
        ref = workspace_image_ref(WorkspaceImageProvider.BUILDFLOOR)
        assert ref.split("@")[0] == "ghcr.io/agentparadise/agentic-workspace-buildfloor"
        assert ref == DEFAULT_WORKSPACE_IMAGE


def test_every_provider_is_pinned() -> None:
    assert set(PINNED_DIGESTS) == set(WorkspaceImageProvider)


def test_no_pin_is_the_pending_placeholder() -> None:
    """RED UNTIL #1417: the switchover must not ship without real digests.

    AW_RELEASE_DIGEST_PENDING exists only so this branch can be prepared before
    agentic-workspace's first release. Fill PINNED_DIGESTS from that release
    run; never delete or skip this test to make the suite green.
    """
    pending = sorted(p.value for p, d in PINNED_DIGESTS.items() if d == AW_RELEASE_DIGEST_PENDING)
    assert not pending, f"TODO(#1417): digests still pending for {pending}"
