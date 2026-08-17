"""Workspace image registry - single source of truth for container image references.

All workspace image names, digests, and GHCR paths are defined here. No other
module should hardcode image strings. To add a new provider image, add an entry
to WorkspaceImageProvider and a matching entry to PINNED_DIGESTS.

See ADR-056: Workspace Tooling Architecture

Why digests and not tags
------------------------
Tags are mutable in OCI by design. agentic-primitives republishes
``:latest`` on every push to its main branch, so a tag-pinned reference means
every merge there silently changes what Syntropic137 runs. That is not a
hypothetical: on 2026-08-16 a regression in the workspace entrypoint reached
``:latest`` and any deployment pulling in that window picked it up.

A digest is the only immutable reference. The registry cannot repoint it,
because the digest *is* the content hash of the image index.

**Pinning ``:latest`` is not supported.** No release process on the publishing
side makes a tag a guarantee; only a digest does.

Bumping a pinned digest
-----------------------
A digest bump is a dependency update and is reviewed like one: a PR that
changes only the constants below, with the new digest in the diff so a
reviewer can see exactly what is changing and check it against the upstream
build.

To bump::

    docker buildx imagetools inspect \\
        ghcr.io/agentparadise/agentic-workspace-claude-cli:latest

Take the top-level ``Digest:`` value (the multi-arch image index digest, not a
per-platform manifest digest), record which agentic-primitives commit produced
it, and open a PR. Signature verification
(``syn_adapters.workspace_backends.image_verification``) runs against the
digest at provision time, so a bump to an unsigned or unexpectedly-built image
fails closed rather than running.

Overriding without a code change
--------------------------------
Operators override the full image reference through the existing workspace
settings, no code change required:

- ``SYN_WORKSPACE_DOCKER_IMAGE`` overrides the claude-cli image
- ``SYN_WORKSPACE_INTERACTIVE_TMUX_IMAGE`` overrides the interactive-tmux image

Both accept any reference form. A locally built image (a bare name such as
``agentic-workspace-claude-cli:dev``) is the supported local-development path:
it has no registry host, was never signed, and signature verification skips it
with a warning rather than blocking it. A *remote* reference is required to be
digest-pinned; a remote tag is rejected, because verifying a tag does not
establish what will actually be pulled.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

# ---------------------------------------------------------------------------
# Registry constants
# ---------------------------------------------------------------------------

GHCR_REGISTRY: str = "ghcr.io"
GHCR_OWNER: str = "agentparadise"
IMAGE_PREFIX: str = "agentic-workspace"


class WorkspaceImageProvider(StrEnum):
    """Available workspace image providers.

    Each provider corresponds to a Docker image built by agentic-primitives.
    """

    CLAUDE_CLI = "claude-cli"
    INTERACTIVE_TMUX = "interactive-tmux"


# ---------------------------------------------------------------------------
# Pinned digests
#
# These are multi-arch image *index* digests, so the same pin resolves on both
# linux/amd64 and linux/arm64. Verified against GHCR on 2026-08-17.
#
# claude-cli       built from agentic-primitives d31c88a, which carries the
#                  capability runtime, the entrypoint `exec` fix (so the agent
#                  process is PID 1 and honours `docker stop -t`) and the
#                  credential-repr fix. Tags :latest and :d31c88a both resolved
#                  to this digest at pin time.
# interactive-tmux built by the same workflow run matrix; it is published to
#                  GHCR (it is one of the two providers in the build matrix of
#                  agentic-primitives .github/workflows/build-workspace-images.yml).
#
# Bump procedure: see the module docstring.
# ---------------------------------------------------------------------------

PINNED_DIGESTS: Final[Mapping[WorkspaceImageProvider, str]] = MappingProxyType(
    {
        WorkspaceImageProvider.CLAUDE_CLI: (
            "sha256:0d53e7a1a9476c5c45cbb7b1467adc004347bef4cf9168c013a6bc7caa5c3f07"
        ),
        WorkspaceImageProvider.INTERACTIVE_TMUX: (
            "sha256:43247b67a415847b609ec60e035750dd4b965c0ceac593ad1f6abf9ff36549ba"
        ),
    }
)


# ---------------------------------------------------------------------------
# Image reference builder
# ---------------------------------------------------------------------------


def workspace_image_ref(
    provider: WorkspaceImageProvider = WorkspaceImageProvider.CLAUDE_CLI,
    tag: str | None = None,
    *,
    digest: str | None = None,
    registry: str = GHCR_REGISTRY,
    owner: str = GHCR_OWNER,
) -> str:
    """Build a fully-qualified image reference for a workspace provider.

    With neither ``tag`` nor ``digest`` supplied this returns the pinned,
    immutable digest reference for the provider. That is the form every
    production code path should use.

    Args:
        provider: Which provider image to reference.
        tag: Explicit tag. Mutable; only for tooling that genuinely wants a
            tag (build scripts, one-off diagnostics). Mutually exclusive
            with ``digest``.
        digest: Explicit ``sha256:...`` digest, overriding the pin.
        registry: Container registry (default: ghcr.io).
        owner: Registry owner/org (default: agentparadise).

    Returns:
        Full image reference, e.g.
        'ghcr.io/agentparadise/agentic-workspace-claude-cli@sha256:0d53...'

    Raises:
        ValueError: If both ``tag`` and ``digest`` are supplied.
    """
    if tag is not None and digest is not None:
        msg = "workspace_image_ref accepts tag or digest, not both"
        raise ValueError(msg)

    repository = f"{registry}/{owner}/{IMAGE_PREFIX}-{provider.value}"

    if tag is not None:
        return f"{repository}:{tag}"

    return f"{repository}@{digest or PINNED_DIGESTS[provider]}"


# ---------------------------------------------------------------------------
# Convenience constants (the most common references)
# ---------------------------------------------------------------------------

DEFAULT_WORKSPACE_IMAGE: str = workspace_image_ref(WorkspaceImageProvider.CLAUDE_CLI)
"""Default workspace image - Claude CLI provider, digest-pinned, from GHCR."""

INTERACTIVE_TMUX_WORKSPACE_IMAGE: str = workspace_image_ref(WorkspaceImageProvider.INTERACTIVE_TMUX)
"""Default interactive-tmux workspace image - digest-pinned, from GHCR.

This provider is published to GHCR by the same agentic-primitives workflow that
publishes claude-cli, so it is pinned and verified identically. Local
development against a locally built ``agentic-workspace-interactive-tmux:<tag>``
still works through ``SYN_WORKSPACE_INTERACTIVE_TMUX_IMAGE``.
"""
