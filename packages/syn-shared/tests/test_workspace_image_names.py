"""Image names must match what agentic-workspace actually publishes.

<<<<<<< HEAD
A workspace image name is a cross-repo contract: agentic-workspace's release
workflow (``.github/workflows/release-images.yml``) declares, per publishing
job, ``PROVIDER: <provider>`` and ``IMAGE: ghcr.io/agentparadise/<name>``, and
this repo has to reference the same ``<name>``. Deriving it from a pattern is
the tempting move and it is wrong - claude-cli publishes as
``agentic-workspace-claude``, because ``agentic-workspace-claude-cli`` is the
GHCR package agentic-primitives already owns. The manifest ``image.tag`` is only
the LOCAL build tag and does not decide the published name.
=======
A workspace image name is a cross-repo contract, and the authoritative source
MOVED when publishing moved.

Under agentic-primitives the repository name came from ``image.tag`` in each
provider manifest, and this file read the manifests. Under agentic-workspace it
does NOT: ``release-images.yml`` sets ``IMAGE:`` per publish job and pushes to
exactly that, while the manifests still carry the old agentic-primitives
values. As of release c5e34284 they disagree outright:

    provider     manifest image.tag            published IMAGE
    claude-cli   agentic-workspace-claude-cli  agentic-workspace-claude
    omni-agent   omni-agent-workspace          agentic-workspace-omni-agent
    toolchain    agentic-workspace-toolchain   agentic-workspace-toolchain

So these tests read the WORKFLOW, which is what actually decides the
repository a digest lands in. Reading the manifests would assert against
strings nothing publishes, and would have "verified" two names that do not
exist in the registry.

The exception also moved: agentic-primitives made omni-agent the odd one out,
agentic-workspace makes claude-cli the odd one out. A test that only checked
"an override exists" would pass before and after while naming the wrong
image.
>>>>>>> origin/main

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

<<<<<<< HEAD
pytestmark = pytest.mark.unit

=======
#: ``release-images.yml`` in the PUBLISHING repository is what decides the
#: repository each digest is pushed to. Not the provider manifests: under
#: agentic-workspace those still carry agentic-primitives names and disagree
#: with what is published.
>>>>>>> origin/main
_RELEASE_WORKFLOW = (
    Path(__file__).resolve().parents[3]
    / "lib"
    / "agentic-workspace"
    / ".github"
    / "workflows"
    / "release-images.yml"
<<<<<<< HEAD
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
=======
)


def _published_repositories() -> dict[str, str] | None:
    """``{provider: repository}`` as the publishing workflow declares it.

    Each publish job sets ``PROVIDER:`` and ``IMAGE:`` in its ``env:`` block.
    Pairing them positionally - the provider most recently seen owns the next
    IMAGE - is enough for that shape and needs no YAML dependency.

    Returns None when the submodule is not checked out.
    """
    if not _RELEASE_WORKFLOW.is_file():
        return None
    found: dict[str, str] = {}
    provider: str | None = None
    for raw in _RELEASE_WORKFLOW.read_text().splitlines():
        stripped = raw.strip()
        if stripped.startswith("PROVIDER:"):
            provider = stripped.split(":", 1)[1].strip().strip("\"'")
        elif stripped.startswith("IMAGE:") and provider is not None:
            ref = stripped.split(":", 1)[1].strip().strip("\"'")
            found[provider] = ref.rsplit("/", 1)[-1]
            provider = None
    return found or None
>>>>>>> origin/main


@pytest.mark.parametrize("provider", list(WorkspaceImageProvider))
<<<<<<< HEAD
def test_image_name_matches_the_release_workflow(provider: WorkspaceImageProvider) -> None:
    published = _published_names()
    assert provider.value in published, (
        f"agentic-workspace's release workflow does not publish {provider.value!r}; "
        f"it publishes {sorted(published)}. A pinned provider nobody publishes cannot "
        f"be bumped."
    )
=======
def test_image_name_matches_what_the_publisher_pushes(provider: WorkspaceImageProvider) -> None:
    published = _published_repositories()
    if published is None:
        pytest.skip("lib/agentic-workspace is not checked out")
    if provider.value not in published:
        pytest.fail(
            f"{provider.value}: no publish job in release-images.yml declares this "
            f"provider. Declared providers: {sorted(published)}. Either the provider "
            f"is not published at all - in which case it must not carry a pinned "
            f"digest - or the workflow renamed its PROVIDER value."
        )

>>>>>>> origin/main
    assert workspace_image_name(provider) == published[provider.value], (
        f"{provider.value}: this repo references {workspace_image_name(provider)!r} but "
        f"agentic-workspace publishes {published[provider.value]!r}. Add or correct an "
        f"entry in IMAGE_NAME_OVERRIDES - do NOT change the derivation pattern, other "
        f"providers depend on it."
    )


<<<<<<< HEAD
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
=======
@pytest.mark.unit
def test_every_published_provider_is_known_here() -> None:
    """A provider the publisher ships but this repo does not model is a gap.

    The reverse of the test above. Without it, agentic-workspace could add a
    fourth image and nothing here would notice, which is how toolchain sat
    unpinned and unmodelled while it was already being built.
    """
    published = _published_repositories()
    if published is None:
        pytest.skip("lib/agentic-workspace is not checked out")

    known = {p.value for p in WorkspaceImageProvider}
    unmodelled = sorted(set(published) - known)
    assert not unmodelled, (
        f"agentic-workspace publishes providers this repo does not model: "
        f"{unmodelled}. Add them to WorkspaceImageProvider with a PINNED_DIGESTS "
        f"entry, or record here why they are deliberately not consumed."
    )


@pytest.mark.unit
class TestClaudeCliIsTheKnownException:
    """Pin the specific case that motivates the override map.

    Under agentic-workspace the odd one out is claude-cli, not omni-agent. The
    exception swapped when publishing moved, so asserting only that *some*
    override exists would have passed before and after while pointing at the
    wrong image.
    """

    def test_claude_cli_does_not_use_the_derived_name(self) -> None:
        name = workspace_image_name(WorkspaceImageProvider.CLAUDE_CLI)
        assert name == "agentic-workspace-claude"
        assert name != "agentic-workspace-claude-cli"

    def test_claude_cli_ref_is_fully_qualified(self) -> None:
        # Assert the repository, not the whole reference. Refs are digest
        # pinned and a digest changes on every release; this is about the NAME.
        ref = workspace_image_ref(WorkspaceImageProvider.CLAUDE_CLI)
        assert ref.split("@")[0] == "ghcr.io/agentparadise/agentic-workspace-claude"
        assert "@sha256:" in ref

    def test_the_old_publishers_name_is_not_used(self) -> None:
        """The agentic-primitives repositories still exist and still resolve.

        Pulling one would succeed, and cosign would accept it while the
        cutover admits both signing identities, so nothing downstream would
        report the mistake. This is the assertion that catches it.
        """
        for provider in WorkspaceImageProvider:
            name = workspace_image_name(provider)
            assert name != "omni-agent-workspace"
            assert name != "agentic-workspace-claude-cli"


@pytest.mark.unit
class TestDerivedProvidersUnchanged:
    """The override map must not disturb providers that are already correct."""

    def test_omni_agent_now_derives(self) -> None:
        ref = workspace_image_ref(WorkspaceImageProvider.OMNI_AGENT)
        assert ref.split("@")[0] == "ghcr.io/agentparadise/agentic-workspace-omni-agent"
>>>>>>> origin/main
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
