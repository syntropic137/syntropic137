"""Workspace image registry - single source of truth for container image references.

All workspace image names, digests, and GHCR paths are defined here. No other
module should hardcode image strings. To add a new provider image, add an entry
to WorkspaceImageProvider and a matching entry to PINNED_DIGESTS.

See ADR-056: Workspace Tooling Architecture

Why digests and not tags
------------------------
Tags are mutable in OCI by design, so a tag-pinned reference means an upstream
publish silently changes what Syntropic137 runs. That is not a hypothetical: on
2026-08-16 a regression in the workspace entrypoint reached a mutable tag and
any deployment pulling in that window picked it up.

Which upstream tag moves when is itself a trap, and it differs per branch.
agentic-primitives publishes ``:edge`` and the commit SHA from ``main``, and
moves ``:latest`` only from its ``release`` branch. So ``:latest`` is not
"the newest image" - it can be considerably OLDER than what main has built.
On 2026-08-19 ``:latest`` for omni-agent still resolved to an image carrying
agentic-session-exporter v0.1.1, which wrote an out-of-spec
``origin.environment``, while main had already built v0.2.1. A digest taken
from ``:latest`` that day would have pinned the defect.

Take digests from the upstream build run, never from a mutable tag.

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

Both accept any reference form. A registry reference is required to be
digest-pinned; a registry tag is rejected, because verifying a tag does not
establish what will actually be pulled.

A locally built image (a bare name such as ``agentic-workspace-claude-cli:dev``)
is the supported local-development path, but it is not inferred from the
reference: it must be turned on with
``SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES=true``, and the image must already exist
on the Docker host, because a reference with no registry host is otherwise
pulled from Docker Hub. See
``syn_adapters.workspace_backends.image_verification`` for the policy.
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
    OMNI_AGENT = "omni-agent"
    """Multi-harness image: claude AND codex on the shared ADR-040 runtime.

    The claude-cli image carries a codex binary too, so codex phases run there
    today. Omni is the image where hosting both harnesses is the contract
    rather than a side effect - its manifest treats one working harness as a
    broken image, not a degraded one.

    Published as ``omni-agent-workspace``, NOT ``agentic-workspace-omni-agent``
    - see IMAGE_NAME_OVERRIDES.
    """


# Most providers publish as ``<IMAGE_PREFIX>-<provider>``. omni-agent does not:
# agentic-primitives takes its repository name from ``image.tag`` in the
# provider manifest, which reads ``omni-agent-workspace``, and its build matrix
# publishes under exactly that. Deriving the name would silently produce
# ``agentic-workspace-omni-agent``, which does not exist - the workspace would
# fail to pull at provision time, far from this file.
IMAGE_NAME_OVERRIDES: dict[WorkspaceImageProvider, str] = {
    WorkspaceImageProvider.OMNI_AGENT: "omni-agent-workspace",
}


def workspace_image_name(provider: WorkspaceImageProvider) -> str:
    """Repository name (no registry, owner, or tag) for a provider image."""
    return IMAGE_NAME_OVERRIDES.get(provider, f"{IMAGE_PREFIX}-{provider.value}")


# ---------------------------------------------------------------------------
# Pinned digests
#
# These are multi-arch image *index* digests, so the same pin resolves on both
# linux/amd64 and linux/arm64. Each entry below records its OWN verification
# date; there is no single date for the whole table, because pins move
# independently.
#
# claude-cli       built from agentic-primitives d31c88a, which carries the
#                  capability runtime, the entrypoint `exec` fix (so the agent
#                  process is PID 1 and honours `docker stop -t`) and the
#                  credential-repr fix. Tags :latest and :d31c88a both resolved
#                  to this digest at pin time.
# interactive-tmux built by the same workflow run matrix; it is published to
#                  GHCR (it is one of the two providers in the build matrix of
#                  agentic-primitives .github/workflows/build-workspace-images.yml).
# omni-agent       built from agentic-primitives a6b5d3f, omni-agent manifest
#                  1.3.0. Verified on 2026-08-21 by running the binary OUT OF
#                  THIS DIGEST on BOTH architectures: linux/amd64 and
#                  linux/arm64 each report
#                  "apss-session-exporter 0.5.0 (APS-V1-0004 SCS 1.0)".
#
#                  v0.5.0 adds a `sessions` array to the exporter's --json
#                  result at RESULT_SCHEMA_VERSION 2: the session ids the store
#                  CONFIRMED during the sweep. syn137 reads it into
#                  AuthoritativeCapture.agent_session_ids and surfaces it at
#                  /capture/status, which is how a phase is related to the
#                  agent-native transcripts it produced. syn137's own
#                  session_id is a uuid4 the agent never sees, so the host's
#                  identifier and the store's are disjoint namespaces. Store
#                  envelopes already carry execution_id, workspace_id and
#                  phase_id as host-supplied TAGS, so this list is not the only
#                  route from a phase to its sessions - it is the only one that
#                  records the agent-native session IDS confirmed during the
#                  sweep, rather than identifying the run that produced them.
#                  Note one session id can cover several envelopes, so it is an
#                  id list and not a transcript count.
#
#                  ROLLOUT ORDER WAS SATISFIED BEFORE THIS PIN. capture_result
#                  accepts result schema 1 AND 2 (#862, merged). Pinning an
#                  image that emits schema 2 against a build that accepted only
#                  1 would have turned every capture probe into a parse error,
#                  and a document that will not parse is indistinguishable from
#                  a capture that never happened.
#
#                  The exporter image itself was verified before it went into
#                  omni: both platforms present, both binaries at mode 0755,
#                  and cosign verifying keyless against
#                  release.yml@refs/tags/v0.5.0. That check is done by hand
#                  because the exporter's own release gate builds a scratch
#                  image rather than the release context
#                  (agentic-session-exporter#22).
#
#                  Previous pin, for the record:
# omni-agent       built from agentic-primitives 1bc7253. Verified on
#                  2026-08-20 by running OUT OF THIS DIGEST: the baked
#                  exporter reports "apss-session-exporter 0.3.0", and the
#                  session-store finalizer both understands the exporter's new
#                  exit 3 and parses its new `unconfirmed` counter.
#
#                  v0.3.0 is the release that stops recording a REFUSED
#                  transcript as sent. Before it, the uploader marked every
#                  item in a successful batch as done, rejections included, so
#                  the next sweep skipped the refused transcript as
#                  skipped_unchanged and reported success. One transient
#                  rejection became permanent silent absence from the store.
#
#                  The image carries both halves deliberately: an exporter
#                  emitting exit 3 alongside a finalizer that would otherwise
#                  read it as a total upload failure would report every partial
#                  capture as a failed one.
#
#                  Previous pin, for the record:
# omni-agent       built from agentic-primitives 066e977, the first omni image
#                  carrying agentic-session-exporter v0.2.1. Verified on
#                  2026-08-19 by running the binary OUT OF THIS DIGEST:
#                  reports "apss-session-exporter 0.2.1", and
#                  SESSION_STORE_ORIGIN_ENV=laptop is refused with
#                  InvalidEnvironment("laptop") rather than written into every
#                  envelope. The previous pin shipped v0.1.1, which defaulted
#                  origin.environment to "laptop" - not one of the four classes
#                  APS-V1-0004 4.2.1 defines - so sessions captured with the
#                  default were out of spec on a REQUIRED field.
#
#                  Do NOT resolve omni-agent through :latest. The build matrix
#                  pushes :edge and the commit SHA from main, and :latest moves
#                  only on a release, so :latest currently resolves to an OLDER
#                  image than this pin. Take digests from the build run, not
#                  from a mutable tag.
#
# Bump procedure: see the module docstring.
# ---------------------------------------------------------------------------

PINNED_DIGESTS: Final[Mapping[WorkspaceImageProvider, str]] = MappingProxyType(
    {
        WorkspaceImageProvider.CLAUDE_CLI: (
            "sha256:88bb708151caf11eb77bb2ee912e35319a3745d1212ee261e508f1623dc5c81d"
        ),
        WorkspaceImageProvider.INTERACTIVE_TMUX: (
            "sha256:222c0ec72ebf786c8a37dec359e14326c9efbb7ec57a523da7227ba7531c43a4"
        ),
        WorkspaceImageProvider.OMNI_AGENT: (
            "sha256:7b82a14dd65cdd6bdee141a87677055e3110c0cb86d52b33765e6850a773aaea"
        ),
    }
)


#: The apss-session-exporter baked into each pinned image, for the providers
#: that carry one at all. Verified by running OUT OF the digest above and
#: reading what the binary reports, the same way the pin itself is verified.
#:
#: It lives here, beside the digest, because the two move together: an image
#: bump that leaves this stale makes every report of it name a version nothing
#: is running. Deliberately NOT recovered by reading the prose above - the
#: comment block keeps previous pins on purpose, so a text search returns
#: whichever version happens to appear first and silently reports a historical
#: one after any reordering.
PINNED_EXPORTER_VERSIONS: Final[Mapping[WorkspaceImageProvider, str]] = MappingProxyType(
    {
        WorkspaceImageProvider.OMNI_AGENT: "0.5.0",
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

    # workspace_image_name, not f"{IMAGE_PREFIX}-{provider.value}": omni-agent
    # publishes as `omni-agent-workspace`, so the prefix pattern is wrong for it.
    repository = f"{registry}/{owner}/{workspace_image_name(provider)}"

    if tag is not None:
        return f"{repository}:{tag}"

    return f"{repository}@{digest or PINNED_DIGESTS[provider]}"


# ---------------------------------------------------------------------------
# Convenience constants (the most common references)
# ---------------------------------------------------------------------------

DEFAULT_WORKSPACE_IMAGE: str = workspace_image_ref(WorkspaceImageProvider.OMNI_AGENT)
"""Default workspace image - omni-agent, digest-pinned, from GHCR.

Omni hosts BOTH harnesses (claude and codex) on the shared ADR-040 capability
runtime. claude-cli happens to carry a codex binary, so codex phases ran there
before this default moved, but that was a side effect rather than a contract:
omni's manifest treats an image with one working harness as broken, not
degraded. Making omni the default is what turns a codex phase into a supported
configuration.

Operators pin a different image with ``SYN_WORKSPACE_DOCKER_IMAGE``. It must be
a digest reference; a registry tag is rejected.
"""

INTERACTIVE_TMUX_WORKSPACE_IMAGE: str = workspace_image_ref(WorkspaceImageProvider.INTERACTIVE_TMUX)
"""Default interactive-tmux workspace image - digest-pinned, from GHCR.

This provider is published to GHCR by the same agentic-primitives workflow that
publishes claude-cli, so it is pinned and verified identically. Local
development against a locally built ``agentic-workspace-interactive-tmux:<tag>``
still works through ``SYN_WORKSPACE_INTERACTIVE_TMUX_IMAGE`` together with
``SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES=true``.
"""
