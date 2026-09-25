"""Image names must match what agentic-workspace actually publishes.

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

Getting it wrong fails at workspace provision time, in a container pull error
far from the constant that caused it. These tests read the submodule manifests
and compare, so a rename upstream fails here instead.

Skipped when the submodule is not checked out, so a shallow clone does not fail
the suite - the CI job that has submodules is the one that enforces this.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syn_shared.settings.workspace_images import (
    PINNED_DIGESTS,
    WorkspaceImageProvider,
    workspace_image_name,
    workspace_image_ref,
)

#: ``release-images.yml`` in the PUBLISHING repository is what decides the
#: repository each digest is pushed to. Not the provider manifests: under
#: agentic-workspace those still carry agentic-primitives names and disagree
#: with what is published.
_RELEASE_WORKFLOW = (
    Path(__file__).resolve().parents[3]
    / "lib"
    / "agentic-workspace"
    / ".github"
    / "workflows"
    / "release-images.yml"
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


@pytest.mark.unit
@pytest.mark.parametrize("provider", list(WorkspaceImageProvider))
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

    assert workspace_image_name(provider) == published[provider.value], (
        f"{provider.value}: this repo references {workspace_image_name(provider)!r} but "
        f"agentic-workspace publishes {published[provider.value]!r}. Add or correct an "
        f"entry in IMAGE_NAME_OVERRIDES - do NOT change the derivation pattern, other "
        f"providers depend on it."
    )


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
        assert "@sha256:" in ref


@pytest.mark.unit
class TestEveryProviderIsPinned:
    """A provider without a digest pin is a KeyError at workspace provision time.

    ``workspace_image_ref`` subscripts PINNED_DIGESTS directly, so adding an
    enum member without a matching pin does not fail here - it fails far away,
    when a workspace is being created. This test moves that failure to the
    place that can fix it.
    """

    def test_all_providers_have_a_pinned_digest(self) -> None:
        missing = [p.value for p in WorkspaceImageProvider if p not in PINNED_DIGESTS]
        assert not missing, (
            f"providers with no PINNED_DIGESTS entry: {missing}. "
            f"Resolve the multi-arch index digest with `docker buildx imagetools "
            f"inspect` and add it, or workspace provision raises KeyError."
        )

    def test_every_provider_resolves_to_a_digest_reference(self) -> None:
        for provider in WorkspaceImageProvider:
            ref = workspace_image_ref(provider)
            assert "@sha256:" in ref, f"{provider.value} is not digest-pinned: {ref}"
