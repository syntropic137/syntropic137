"""Image names must match what agentic-primitives actually publishes.

A workspace image name is a cross-repo contract: agentic-primitives decides the
repository name from ``image.tag`` in each provider manifest, and this repo has
to reference the same string. Deriving it from a pattern is the tempting move
and it is wrong - omni-agent publishes as ``omni-agent-workspace``, not
``agentic-workspace-omni-agent``.

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

_PROVIDERS_DIR = (
    Path(__file__).resolve().parents[3] / "lib" / "agentic-primitives" / "providers" / "workspaces"
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
        pytest.skip(f"agentic-primitives manifest for {provider.value} not available")

    assert workspace_image_name(provider) == tag, (
        f"{provider.value}: this repo references {workspace_image_name(provider)!r} but "
        f"agentic-primitives publishes {tag!r}. Add or correct an entry in "
        f"IMAGE_NAME_OVERRIDES - do NOT change the derivation pattern, other "
        f"providers depend on it."
    )


@pytest.mark.unit
class TestOmniIsTheKnownException:
    """Pin the specific case that motivated the override map."""

    def test_omni_does_not_use_the_derived_name(self) -> None:
        name = workspace_image_name(WorkspaceImageProvider.OMNI_AGENT)
        assert name == "omni-agent-workspace"
        assert name != "agentic-workspace-omni-agent"

    def test_omni_ref_is_fully_qualified(self) -> None:
        # Assert the repository, not the whole reference. Refs are digest
        # pinned, and a digest changes on every release; this test is about
        # the image NAME being the unprefixed one.
        ref = workspace_image_ref(WorkspaceImageProvider.OMNI_AGENT)
        assert ref.split("@")[0] == "ghcr.io/agentparadise/omni-agent-workspace"
        assert "@sha256:" in ref


@pytest.mark.unit
class TestDerivedProvidersUnchanged:
    """The override map must not disturb providers that were already correct."""

    def test_claude_cli_still_derives(self) -> None:
        ref = workspace_image_ref(WorkspaceImageProvider.CLAUDE_CLI)
        assert ref.split("@")[0] == "ghcr.io/agentparadise/agentic-workspace-claude-cli"
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
