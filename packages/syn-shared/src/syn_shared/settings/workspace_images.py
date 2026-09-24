"""Workspace image registry - single source of truth for container image references.

All workspace image names, digests, and GHCR paths are defined here. No other
module should hardcode image strings. To add a new provider image, add an entry
to WorkspaceImageProvider and a matching entry to PINNED_DIGESTS.

See ADR-056: Workspace Tooling Architecture

Publisher
---------
Workspace images are built and signed by AgentParadise/agentic-workspace
(vendored at ``lib/agentic-workspace``). Its release workflow
(``.github/workflows/release-images.yml``) publishes ONLY on a push to the
protected ``release`` branch, signs each index digest keyless with cosign, and
never pushes ``latest``. Tags are ``<commit sha>``, ``<manifest version>`` and
``v<repo version>``. The former publisher, AgentParadise/agentic-primitives,
remains available as a rollback target only (see "Rollback" below).

Why digests and not tags
------------------------
Tags are mutable in OCI by design, so a tag-pinned reference means an upstream
publish silently changes what Syntropic137 runs. That is not a hypothetical: on
2026-08-16 a regression in the workspace entrypoint reached a mutable tag and
any deployment pulling in that window picked it up.

Which upstream tag moves when is itself a trap. The legacy agentic-primitives
publisher moved ``:edge`` from main and ``:latest`` only from its release
branch, so on 2026-08-19 ``:latest`` for omni-agent still resolved to an image
carrying agentic-session-exporter v0.1.1 while main had already built v0.2.1. A
digest taken from ``:latest`` that day would have pinned the defect.
agentic-workspace publishes no ``:latest`` at all, but its version tags are
still registry references that can be re-pointed, not consumer pins.

Take digests from the upstream release run, never from a mutable tag.

A digest is the only immutable reference. The registry cannot repoint it,
because the digest *is* the content hash of the image index.

**Pinning a tag is not supported.** No release process on the publishing side
makes a tag a guarantee; only a digest does.

Bumping a pinned digest
-----------------------
A digest bump is a dependency update and is reviewed like one: a PR that
changes the constants below and the ``lib/agentic-workspace`` gitlink together,
with the new digests in the diff so a reviewer can check them against the
upstream release run.

1. Merge the agentic-workspace change to its ``main``, then promote it to
   ``release`` by PR. The push to ``release`` runs ``release-images.yml``.
2. From that run's summary take each image's top-level index digest (the
   multi-arch index, not a per-platform manifest). Cross-check with::

       docker buildx imagetools inspect \\
           ghcr.io/agentparadise/agentic-workspace-buildfloor:<release commit sha>

3. Move ``lib/agentic-workspace`` to that same release commit. Every pin must
   come from the one revision the submodule ships
   (``scripts/check_pinned_image_channels.py`` enforces it).
4. Record the commit, run id and the CLI / exporter versions read OUT OF the
   digest in the comment beside the pin.

Signature verification (``syn_adapters.workspace_backends.image_verification``)
runs against the digest at provision time, so a bump to an unsigned or
unexpectedly-built image fails closed rather than running.

Rollback to agentic-primitives
------------------------------
The last agentic-primitives pins are kept below as ``AP_ROLLBACK_IMAGES``
(release-branch build of AP 6b9f81e, omni-agent 1.7.0). Rolling back is a
configuration change, no code revert and no image rebuild:

1. Drain in-flight executions (no phase may straddle the swap).
2. Set, in the deployment's ``.env``::

       SYN_WORKSPACE_DOCKER_IMAGE=<AP_ROLLBACK_IMAGES[OMNI_AGENT]>
       SYN_IMAGE_VERIFY_CERTIFICATE_IDENTITY_REGEXP=<AGENTIC_PRIMITIVES_IDENTITY_REGEXP>

   (both values printed by
   ``uv run python -c "from syn_shared.settings.workspace_images import *;
   print(AP_ROLLBACK_IMAGES)"`` and
   ``syn_shared.settings.image_verification.AGENTIC_PRIMITIVES_IDENTITY_REGEXP``).
3. Restart the API; ``syn doctor`` reports the image actually configured.

The AP omni image lacks the buildfloor toolchain (C toolchain, rustup, pnpm,
bun), so workflows that compile native code regress to their pre-switchover
behaviour under rollback. Everything else - entrypoint contract, capability
runtime, session-store, exporter 0.5.0 - is the same contract.

Overriding without a code change
--------------------------------
Operators override the full image reference through the existing workspace
settings, no code change required:

- ``SYN_WORKSPACE_DOCKER_IMAGE`` overrides the default workspace image

It accepts any reference form. A registry reference is required to be
digest-pinned; a registry tag is rejected, because verifying a tag does not
establish what will actually be pulled.

A locally built image (a bare name such as ``agentic-workspace-buildfloor:dev``)
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

    Each provider corresponds to a Docker image built and signed by
    agentic-workspace's release workflow.
    """

    CLAUDE_CLI = "claude-cli"
    """Claude-only image. Published as ``agentic-workspace-claude`` - see
    IMAGE_NAME_OVERRIDES."""

    OMNI_AGENT = "omni-agent"
    """Multi-harness image: claude AND codex on the shared ADR-040 runtime.

    Omni is the image where hosting both harnesses is the contract rather than
    a side effect - its manifest treats one working harness as a broken image,
    not a degraded one.
    """

    BUILDFLOOR = "buildfloor"
    """omni-agent plus a native build floor - the DEFAULT workspace image.

    Built FROM the exact omni-agent digest published in the same release run,
    adding build-essential, pkg-config, unzip, rustup (no toolchain; the
    repository's rust-toolchain.toml chooses), pnpm via corepack and bun. A
    compile smoke (cargo build, pnpm install, bun) gates publication on amd64
    and arm64. Being a strict superset of omni, it can run every phase omni
    can, plus repositories whose own gates compile native code.
    """


# Most providers publish as ``<IMAGE_PREFIX>-<provider>``. claude-cli does not:
# agentic-workspace's release workflow publishes it as ``agentic-workspace-claude``
# because ``agentic-workspace-claude-cli`` is the package name agentic-primitives
# already owns on GHCR. Deriving the name would silently pull AP's image (or
# fail signature verification against the AW identity), far from this file.
IMAGE_NAME_OVERRIDES: dict[WorkspaceImageProvider, str] = {
    WorkspaceImageProvider.CLAUDE_CLI: f"{IMAGE_PREFIX}-claude",
}


def workspace_image_name(provider: WorkspaceImageProvider) -> str:
    """Repository name (no registry, owner, or tag) for a provider image."""
    return IMAGE_NAME_OVERRIDES.get(provider, f"{IMAGE_PREFIX}-{provider.value}")


# ---------------------------------------------------------------------------
# Pinned digests
#
# These are multi-arch image *index* digests, so the same pin resolves on both
# linux/amd64 and linux/arm64. Each entry records its OWN verification date;
# there is no single date for the whole table, because pins move independently.
# ---------------------------------------------------------------------------

#: Placeholder for a digest that does not exist yet. Syntactically a digest so
#: every reference builds, but no registry holds it: a pull or a cosign verify
#: of it fails closed, and ``test_no_pin_is_the_pending_placeholder`` keeps the
#: suite red until it is gone. It must never reach a release.
AW_RELEASE_DIGEST_PENDING: Final[str] = "sha256:" + "0" * 64

# TODO(#1417): fill all three from the first agentic-workspace release run
# (push to `release`, release-images.yml) and move lib/agentic-workspace to that
# release commit in the same change. Record commit, run id, and the claude /
# codex / exporter versions read OUT OF each digest, as the AP history below
# does. Expected from AW omni-agent manifest 1.7.1 (claude 2.1.281, codex
# 0.156.1, apss-session-exporter 0.5.0) and buildfloor manifest 1.0.0.
PINNED_DIGESTS: Final[Mapping[WorkspaceImageProvider, str]] = MappingProxyType(
    {
        WorkspaceImageProvider.CLAUDE_CLI: AW_RELEASE_DIGEST_PENDING,
        WorkspaceImageProvider.OMNI_AGENT: AW_RELEASE_DIGEST_PENDING,
        WorkspaceImageProvider.BUILDFLOOR: AW_RELEASE_DIGEST_PENDING,
    }
)


#: The apss-session-exporter baked into each pinned image, for the providers
#: that carry one at all. Verified by running OUT OF the digest above and
#: reading what the binary reports, the same way the pin itself is verified.
#: buildfloor inherits omni's exporter unchanged (it is built FROM omni).
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
        WorkspaceImageProvider.BUILDFLOOR: "0.5.0",
    }
)


# ---------------------------------------------------------------------------
# Rollback: the last agentic-primitives pins
#
# Full references, because AP publishes under different repository names
# (omni as `omni-agent-workspace`) and signs with a different identity
# (image_verification.AGENTIC_PRIMITIVES_IDENTITY_REGEXP). Procedure: module
# docstring, "Rollback to agentic-primitives". Remove once AP stops publishing
# workspace images and the rollback window has closed.
#
# ---------------------------------------------------------------------------

AP_ROLLBACK_IMAGES: Final[Mapping[WorkspaceImageProvider, str]] = MappingProxyType(
    {
        WorkspaceImageProvider.CLAUDE_CLI: (
            "ghcr.io/agentparadise/agentic-workspace-claude-cli@sha256:"
            "a0ec2333a0e8d9169eda5ce8faf147a67a55b93368d04ba9285338cd207c9341"
        ),
        WorkspaceImageProvider.OMNI_AGENT: (
            "ghcr.io/agentparadise/omni-agent-workspace@sha256:"
            "898aeef61dd057546ef0db7a84467c7d05cb8bb71452a4a3bfd9789343eb912a"
        ),
    }
)

# History of the agentic-primitives pins, kept for the record and because the
# first entry is what AP_ROLLBACK_IMAGES holds.
#
# BOTH pins below were taken on 2026-09-24 from the release-branch build run
# 36040151207 of agentic-primitives 6b9f81e (release PR #425), and both carry
# agentic.image.channel=release and revision 6b9f81e on linux/amd64 AND
# linux/arm64. cosign verify passes for each against
# AGENTIC_PRIMITIVES_IDENTITY_REGEXP (now the rollback identity).
#
# omni-agent       omni-agent manifest 1.7.0. Verified by running OUT OF THIS
#                  DIGEST on both architectures: "2.1.281 (Claude Code)",
#                  "codex-cli 0.156.1", "apss-session-exporter 0.5.0". This is
#                  the image that knows the new defaults: claude-code 2.1.280+
#                  resolves the `opus` alias to claude-opus-5-5, and codex
#                  0.156.1 is the first CLI whose catalog carries gpt-6-sol
#                  (the target of the `gpt-sol` alias). An older image fails
#                  every codex phase that takes the default model.
# claude-cli       claude-cli manifest 2.1.4, CLIs unchanged (claude 2.1.126,
#                  codex 0.144.6). Re-pinned only because every pin must come
#                  from the one revision the submodule ships
#                  (scripts/check_pinned_image_channels.py). Its codex
#                  0.144.6 predates gpt-6-sol, so a codex phase on the default
#                  model cannot run in this image; codex phases belong on
#                  omni-agent (the DEFAULT_WORKSPACE_IMAGE).
#
#                  Previous pins, for the record:
# claude-cli       built from agentic-primitives d31c88a, which carries the
#                  capability runtime, the entrypoint `exec` fix (so the agent
#                  process is PID 1 and honours `docker stop -t`) and the
#                  credential-repr fix. Tags :latest and :d31c88a both resolved
#                  to this digest at pin time.
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
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Image reference builder
# ---------------------------------------------------------------------------


def workspace_image_ref(
    provider: WorkspaceImageProvider = WorkspaceImageProvider.BUILDFLOOR,
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

    # workspace_image_name, not f"{IMAGE_PREFIX}-{provider.value}": claude-cli
    # publishes as `agentic-workspace-claude`, so the prefix pattern is wrong for it.
    repository = f"{registry}/{owner}/{workspace_image_name(provider)}"

    if tag is not None:
        return f"{repository}:{tag}"

    return f"{repository}@{digest or PINNED_DIGESTS[provider]}"


# ---------------------------------------------------------------------------
# Convenience constants (the most common references)
# ---------------------------------------------------------------------------


DEFAULT_WORKSPACE_PROVIDER: Final[WorkspaceImageProvider] = WorkspaceImageProvider.BUILDFLOOR
"""The provider behind DEFAULT_WORKSPACE_IMAGE, for code that reports on it."""

DEFAULT_WORKSPACE_IMAGE: str = workspace_image_ref(DEFAULT_WORKSPACE_PROVIDER)
"""Default workspace image - buildfloor, digest-pinned, from GHCR.

buildfloor is omni-agent (claude AND codex on the shared ADR-040 capability
runtime) plus a native build floor, built FROM the exact omni digest of the
same release run. As a strict superset it runs every phase omni runs, and
additionally repositories whose own gates compile native code (cargo, pnpm,
bun). Per-phase image selection is deliberately not offered: one default image
keeps what a workflow ran reproducible from the pin alone.

Operators pin a different image with ``SYN_WORKSPACE_DOCKER_IMAGE``. It must be
a digest reference; a registry tag is rejected.
"""
