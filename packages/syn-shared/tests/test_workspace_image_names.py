"""Image names must match what agentic-workspace actually publishes.

A workspace image name is a cross-repo contract: the publisher decides the
repository name from ``image.tag`` in each provider manifest, and this repo has
to reference the same string. Deriving it from a pattern is the tempting move
and it is wrong - under agentic-workspace, claude-cli publishes as
``agentic-workspace-claude``, not ``agentic-workspace-claude-cli``.

The exception moved when publishing moved. agentic-primitives published
omni-agent as ``omni-agent-workspace`` and claude-cli as the derived
``agentic-workspace-claude-cli``; agentic-workspace publishes omni-agent as the
derived ``agentic-workspace-omni-agent`` and claude-cli as
``agentic-workspace-claude``. Reading the manifests rather than trusting either
memory is the whole point of this file.

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

#: Provider manifests live in the repository that PUBLISHES the images. That is
#: agentic-workspace as of 2026-09-25, under a different path from the one
#: agentic-primitives used (``providers/workspaces``).
_PROVIDERS_DIR = (
    Path(__file__).resolve().parents[3]
    / "lib"
    / "agentic-workspace"
    / "implementations"
    / "docker"
    / "images"
)


def _manifest_image_tag(provider: WorkspaceImageProvider) -> str | None:
    """Read ``image.tag`` from a provider manifest without a YAML dependency."""
    manifest = _PROVIDERS_DIR / provider.value / "manifest.yaml"
    if not manifest.is_file():
        return None
    in_image_block = False
    for raw in manifest.read_text().splitlines():
        if raw.startswith("image:"):
            in_image_block = True
            continue
        if in_image_block:
            if raw and not raw[0].isspace():
                break  # dedented out of the image: block
            stripped = raw.strip()
            if stripped.startswith("tag:"):
                return stripped.split(":", 1)[1].strip().strip("\"'")
    return None


@pytest.mark.unit
@pytest.mark.parametrize("provider", list(WorkspaceImageProvider))
def test_image_name_matches_the_provider_manifest(provider: WorkspaceImageProvider) -> None:
    tag = _manifest_image_tag(provider)
    if tag is None:
        pytest.skip(f"agentic-workspace manifest for {provider.value} not available")

    assert workspace_image_name(provider) == tag, (
        f"{provider.value}: this repo references {workspace_image_name(provider)!r} but "
        f"agentic-primitives publishes {tag!r}. Add or correct an entry in "
        f"IMAGE_NAME_OVERRIDES - do NOT change the derivation pattern, other "
        f"providers depend on it."
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
