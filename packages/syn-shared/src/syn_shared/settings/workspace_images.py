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

Which upstream tag moves when is itself a trap, and it differs per publisher.
agentic-workspace, which publishes these images as of 2026-09-25, never
publishes from ``main`` at all and never moves ``:latest``: only a push to its
protected ``release`` branch publishes, and it tags the commit SHA plus the
manifest and repo versions. agentic-primitives, the previous publisher, put
``:edge`` and the commit SHA on ``main`` and moved ``:latest`` only from its
own ``release`` branch, so ``:latest`` there was not "the newest image" and
could be considerably OLDER than what main had built.
On 2026-08-19 ``:latest`` for omni-agent still resolved to an image carrying
agentic-session-exporter v0.1.1, which wrote an out-of-spec
``origin.environment``, while main had already built v0.2.1. A digest taken
from ``:latest`` that day would have pinned the defect.

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
           ghcr.io/agentparadise/agentic-workspace-toolchain:<release commit sha>

   Take the top-level ``Digest:`` value (the multi-arch image index digest,
   not a per-platform manifest digest).
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

The AP omni image lacks the toolchain (C toolchain, rustup, pnpm, bun), so
workflows that compile native code regress to their pre-switchover behaviour
under rollback. Everything else - entrypoint contract, capability runtime,
session-store, exporter 0.5.0 - is the same contract.

When the default provider's pin moves, append the outgoing ``DEFAULT_WORKSPACE_IMAGE``
to ``PREVIOUS_DEFAULT_WORKSPACE_IMAGES`` and regenerate ``.env.example``, so
``just selfhost-update`` moves operators who copied the old default (#1398).
A test fails if ``.env.example`` ever shipped a value that is neither.

Overriding without a code change
--------------------------------
Operators override the full image reference through the existing workspace
settings, no code change required:

- ``SYN_WORKSPACE_DOCKER_IMAGE`` overrides the default workspace image

It accepts any reference form. A registry reference is required to be
digest-pinned; a registry tag is rejected, because verifying a tag does not
establish what will actually be pulled.

A locally built image (a bare name such as ``agentic-workspace-claude:dev``)
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

    TOOLCHAIN = "toolchain"
    """omni-agent plus a compile toolchain, for repositories whose own gates
    build native code.

    Adds a C compiler, rustup (the binary and proxies only - the toolchain
    itself installs on first use from the repository's ``rust-toolchain.toml``),
    pnpm through corepack, and bun. Everything omni carries is inherited
    unchanged, so this is a superset rather than a variant: claude, codex, the
    session exporter and the capability runtime are all the same.

    Called ``buildfloor`` until 2026-09-25. Renamed before anything pinned it.
    """


# Most providers publish as ``<IMAGE_PREFIX>-<provider>``. The authoritative
# name is the ``IMAGE:`` env of the matching publish job in agentic-workspace's
# ``release-images.yml``.
#
# It is NOT ``image.tag`` in the provider manifest. That was true under
# agentic-primitives and is not true here: two of agentic-workspace's manifests
# still carry the old agentic-primitives values and disagree with what is
# actually pushed (AgentParadise/agentic-workspace#5). Trusting them would pin
# ``agentic-workspace-claude-cli`` and ``omni-agent-workspace``, which this
# publisher never pushes to.
#
# The override also moved when publishing moved, and it moved to the OTHER
# provider:
#
#   provider     agentic-primitives            agentic-workspace
#   omni-agent   omni-agent-workspace          agentic-workspace-omni-agent
#   claude-cli   agentic-workspace-claude-cli  agentic-workspace-claude
#   toolchain    (did not exist)               agentic-workspace-toolchain
#
# So omni-agent is now the derived name and needs no entry, while claude-cli is
# the exception. This is not a rename of one repository: all of them exist, and
# pulling the wrong one SUCCEEDS. cosign accepts it too, for as long as the
# cutover admits both signing identities, so nothing downstream reports the
# mistake. test_workspace_image_names.py asserts against the workflow for
# exactly that reason.
IMAGE_NAME_OVERRIDES: dict[WorkspaceImageProvider, str] = {
    WorkspaceImageProvider.CLAUDE_CLI: "agentic-workspace-claude",
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
            "ed7c7f1ef3b2112c16c53ca71036bcdb18eb5a406f94ecc5daf5ac455bf11b19"
        ),
        WorkspaceImageProvider.OMNI_AGENT: (
            "ghcr.io/agentparadise/omni-agent-workspace@sha256:"
            "a6ba94d71507384d33df7abe2050f7255bdae8b81dc5a37dbe92b7972f154773"
        ),
    }
)

# History of the agentic-primitives pins, kept for the record and because the
# first entry is what AP_ROLLBACK_IMAGES holds.
#
#                  Previous pins, for the record:
#
# The last pins built by agentic-primitives, taken on 2026-09-25 from its
# release-branch build run 36159902844 at 09887e6 (release PR #430). Both
# carried agentic.image.channel=release and revision 09887e6 on linux/amd64
# AND linux/arm64, and cosign verify passed against
# AGENTIC_PRIMITIVES_IDENTITY_REGEXP. These are the digests a deployment is
# running until it picks up the cutover.
#
# omni-agent       omni-agent manifest 1.7.1. CLIs unchanged from 1.7.0 and
#                  verified by running OUT OF THIS DIGEST on both
#                  architectures: "2.1.281 (Claude Code)", "codex-cli 0.156.1",
#                  "apss-session-exporter 0.5.0". The release carries
#                  agentic-isolation 0.8.1: `find -H` on the transcript root
#                  (#1415 - the session-store capability symlinks
#                  ~/.codex/sessions, so every codex rollout was invisible and
#                  no codex phase could record the model it ran), plus a mount
#                  guard and a finalizer credential log-leak fix (AP #428).
# claude-cli       claude-cli manifest 2.1.5, CLIs unchanged (claude 2.1.126,
#                  codex 0.144.6). Re-pinned for the single-revision rule; it
#                  still cannot run a default codex phase (see below).
#
#                  Previous pins, for the record:
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

# PUBLISHER CUTOVER, 2026-09-25. The pins below are the first images published
# by agentic-workspace rather than agentic-primitives. Taken from release-branch
# run 36184892658 of agentic-workspace c5e34284 (release PR #4), and all carry
# agentic.image.channel=release and revision c5e34284, read off the published
# index. cosign verify passes for each against the combined identity in
# syn_shared.settings.image_verification, using the agentic-workspace
# alternative.
#
# omni-agent       omni-agent manifest 1.7.1, the SAME manifest version as the
#                  agentic-primitives pin it replaces. Verified by running OUT
#                  OF THIS DIGEST: "2.1.281 (Claude Code)", "codex-cli
#                  0.156.1", "apss-session-exporter 0.5.0", and git, gh, jq,
#                  uv, node and python3 all present. One behavioural
#                  difference from the image it replaces: the Vercel Skills
#                  CLI moves 1.5.14 -> 1.7.0. Skill installation is the only
#                  thing that changes underneath a workflow.
# toolchain       toolchain manifest 1.0.0, published for the FIRST time in
#                  this run. The previous run built it but its arm64 compile
#                  smoke failed, so it was pushed by digest and never signed or
#                  tagged; fail-closed meant there was nothing to pin. Built
#                  FROM the omni digest above, in the same run, and the
#                  workflow verifies omni's signature before building on it.
#                  Verified by running OUT OF THIS DIGEST:
#                  "apss-session-exporter 0.5.0", plus cc, rustup, bun, pnpm,
#                  corepack, claude, codex and skills all present.
# claude-cli       claude-cli manifest 2.1.4, which is one patch BEHIND the
#                  2.1.5 it replaces: agentic-workspace forked before that
#                  manifest bump. Both CLIs are unchanged at claude 2.1.126 and
#                  codex 0.144.6, read off the published labels, so there is no
#                  functional regression. It still cannot run a default codex
#                  phase - codex 0.144.6 predates gpt-6-sol - so codex phases
#                  belong on omni-agent, exactly as before.
# AGENTIC-WORKSPACE v0.2.0, 2026-09-29 (#1398). Taken from release-branch run
# 36640582820 ("Release Workspace Images", push to release, success) of
# agentic-workspace 008ed117 (release PR #12), the commit lib/agentic-workspace
# pins. Re-verified here rather than trusted: `docker buildx imagetools
# inspect` of each v0.2.0 tag returns exactly the digest below (amd64 + arm64),
# every image carries agentic.image.channel=release and revision 008ed117, and
# `cosign verify` (v3.1.3) passes for each against
# AGENTIC_WORKSPACE_IDENTITY_REGEXP with the GitHub Actions OIDC issuer. This
# release carries AW #2 (Codex seccomp + AppArmor sandbox policy), #6
# (conversation preview), #7 (native child lifecycle, journal schema v3) and
# #9 (consumer contracts).
#
# omni-agent       omni-agent manifest 1.10.0. Verified by running OUT OF THIS
#                  DIGEST: "2.1.281 (Claude Code)", "codex-cli 0.156.1",
#                  "apss-session-exporter 0.6.0", skills CLI 1.7.0,
#                  agentic-session-store 0.5.0, syn-delegate, and git, gh, jq,
#                  uv, node and python3 all present. Label
#                  agentic.codex_cli_version=0.156.1, so the provider applies
#                  the Codex sandbox policy (AppArmor hosts: load the profile,
#                  docs/deployment/apparmor-codex-sandbox.md).
# toolchain        toolchain manifest 1.1.0, built FROM omni 1.10.0 in the same
#                  run (label agentic.base.omni.version=1.10.0). Verified by
#                  running OUT OF THIS DIGEST: same claude, codex, exporter
#                  0.6.0, skills 1.7.0 and session store as omni; labels bun
#                  1.3.14, rustup 1.29.1.
# claude-cli       claude-cli manifest 2.1.6. Verified by running OUT OF THIS
#                  DIGEST: "2.1.126 (Claude Code)", "codex-cli 0.144.6",
#                  skills 1.7.0, session store 0.5.0, no exporter (unchanged:
#                  claude-cli never carried one). Codex phases still belong on
#                  omni-agent: codex 0.144.6 predates gpt-6-sol.
#
#                  Previous pins, for the record (publisher cutover above):
#                  claude-cli decf374c, omni-agent 89189b6c, toolchain 27b70b32,
#                  all from agentic-workspace c5e34284.
# AGENTIC-WORKSPACE v0.3.0, 2026-10-02 (#1398). Taken from release-branch run
# 37054033737 ("Release Workspace Images", push to release, success) of
# agentic-workspace 7afde6b6 (release PR #26), the commit lib/agentic-workspace
# pins. Re-verified here rather than trusted: `docker buildx imagetools
# inspect` of each v0.3.0 tag, manifest-version tag and commit tag returns
# exactly the digest below (amd64 + arm64), every image carries
# agentic.image.channel=release and revision 7afde6b6, and `cosign verify`
# (v3.1.3) passes for each against the release-images.yml@refs/heads/release
# identity with the GitHub Actions OIDC issuer. This release carries AW #18
# ($HOME ownership), #22 (depth-three delegation: Codex delegate journal grant
# + network, delegated Claude inherits the parent grant, launch-failure
# reasons claude_nested_auth_unavailable / parent_permissions_unavailable /
# nested_journal_unavailable) and #24 (Claude grandchild transcript root
# grant; AppArmor admits nested <execution>/<workspace> partitions - load the
# updated profile on AppArmor hosts).
#
# omni-agent       omni-agent manifest 1.11.0. Verified by running OUT OF THIS
#                  DIGEST: "2.1.281 (Claude Code)", "codex-cli 0.156.1",
#                  "apss-session-exporter 0.6.0", skills CLI 1.7.0,
#                  agentic-session-store 0.6.0 with the transcript-root grant,
#                  syn-delegate. Label agentic.codex_cli_version=0.156.1.
# toolchain        toolchain manifest 1.2.0, built FROM omni d9395a2e in the
#                  same run (label org.opencontainers.image.base.digest).
#                  Verified by running OUT OF THIS DIGEST: same claude, codex,
#                  exporter 0.6.0, skills 1.7.0 and session store as omni.
# claude-cli       claude-cli manifest 2.1.7. Verified by running OUT OF THIS
#                  DIGEST: "2.1.126 (Claude Code)", "codex-cli 0.144.6",
#                  skills 1.7.0, session store 0.6.0, no exporter (unchanged).
#
#                  Previous pins, for the record: claude-cli c0573ea6,
#                  omni-agent 12e7dc55, toolchain e38b1a45, all from
#                  agentic-workspace 008ed117 (v0.2.0).
PINNED_DIGESTS: Final[Mapping[WorkspaceImageProvider, str]] = MappingProxyType(
    {
        WorkspaceImageProvider.CLAUDE_CLI: (
            "sha256:12a38b8aa4eaa81bda48790410550d2741870d54b3c39925d8fdf9f934b221ff"
        ),
        WorkspaceImageProvider.OMNI_AGENT: (
            "sha256:d9395a2ec9b065cd3865e95476c286566231d943b5ab1d2cce3ba3366066556d"
        ),
        WorkspaceImageProvider.TOOLCHAIN: (
            "sha256:16132cce4470d9375dc2421780915e2d68ccaffb118a4479689e34f8cd20cd44"
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
        WorkspaceImageProvider.OMNI_AGENT: "0.6.0",
        # toolchain is built FROM the omni digest, so it inherits the exporter.
        # Recorded from running the binary in the toolchain image anyway:
        # inheritance is the reason to EXPECT a value, never the evidence for
        # one, and a base-image bump could change it without changing omni.
        WorkspaceImageProvider.TOOLCHAIN: "0.6.0",
    }
)

# ---------------------------------------------------------------------------
# Image reference builder
# ---------------------------------------------------------------------------


def workspace_image_ref(
    provider: WorkspaceImageProvider = WorkspaceImageProvider.TOOLCHAIN,
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


DEFAULT_WORKSPACE_PROVIDER: Final[WorkspaceImageProvider] = WorkspaceImageProvider.TOOLCHAIN
"""The provider behind DEFAULT_WORKSPACE_IMAGE, for code that reports on it."""

DEFAULT_WORKSPACE_IMAGE: str = workspace_image_ref(DEFAULT_WORKSPACE_PROVIDER)
"""Default workspace image - toolchain, digest-pinned, from GHCR.

toolchain is omni-agent (claude AND codex on the shared ADR-040 capability
runtime) plus a native build floor, built FROM the exact omni digest of the
same release run. As a strict superset it runs every phase omni runs, and
additionally repositories whose own gates compile native code (cargo, pnpm,
bun). Per-phase image selection is deliberately not offered: one default image
keeps what a workflow ran reproducible from the pin alone.

Operators pin a different image with ``SYN_WORKSPACE_DOCKER_IMAGE``. It must be
a digest reference; a registry tag is rejected.
"""

#: Every value ``.env.example`` ever shipped for ``SYN_WORKSPACE_DOCKER_IMAGE``
#: before the current default, oldest first (read from the file's history on
#: main, with the commit that introduced each; #1398).
#:
#: WHY: ``.env.example`` carries the default digest, so an operator who copied
#: it has that digest in ``.env``, where it OVERRIDES the code default. Every
#: later pin bump then leaves the deployment on the old image. A value in this
#: set was never an operator's choice, only a copied default, so
#: ``migrate_workspace_image`` may move it to the current default; any other
#: value is a deliberate override and is left alone. Append the outgoing
#: default here in the same change that bumps ``PINNED_DIGESTS``.
PREVIOUS_DEFAULT_WORKSPACE_IMAGES: Final[tuple[str, ...]] = (
    "agentic-workspace-claude-cli:latest",  # de72c95b
    "ghcr.io/agentparadise/agentic-workspace-claude-cli:latest",  # f6b5bee1
    "ghcr.io/agentparadise/agentic-workspace-claude-cli@sha256:0d53e7a1a9476c5c45cbb7b1467adc004347bef4cf9168c013a6bc7caa5c3f07",  # 49a11ed1
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:f73353adfe99fbab00e0d754543d686f5e57e6c30fddbaebdeeff97b644d53e6",  # 6131040a
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:fb1a719e71f251fbc6cbee4025e89a4dee1fbb9217503f3bc511817eea6ee92c",  # c0b5eb17
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:c447f0cb9905791499de29fba4f848cbb1e6829cf2400d82437fe8f4fc6c5948",  # 52fd32e9
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:dd27d01d5655638d9bffbad6a8a521c0466a78de2f797641fa429686afe457a8",  # d780433b
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:70de5883ba60441b4bc5c357fdb5ec8106852d526735cea90d98aeea1652a7d3",  # 648fc035
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:7b82a14dd65cdd6bdee141a87677055e3110c0cb86d52b33765e6850a773aaea",  # fc897f9e
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:83834d632c9218c0b1772e11820c23e703a5304d7c5016ae9a683665f7d5db6f",  # 25718d9d
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:3e88b1c7d8f6ff9648b3337c2220e17e9368aff940ab9fbbebd0d3c9b25bfaed",  # 6d79609e
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:898aeef61dd057546ef0db7a84467c7d05cb8bb71452a4a3bfd9789343eb912a",  # 0a39dd60
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:29b76b43753292ab50de77921b4cd2750446ea2896cb25f8ee0bfa162d537ad0",  # 46615708
    "ghcr.io/agentparadise/omni-agent-workspace@sha256:a6ba94d71507384d33df7abe2050f7255bdae8b81dc5a37dbe92b7972f154773",  # bdd0ba5d
    "ghcr.io/agentparadise/agentic-workspace-omni-agent@sha256:123ab8497e224871b83fc3148774b7be1b59753638f6516673acf5400f049053",  # 9a720d66
    "ghcr.io/agentparadise/agentic-workspace-omni-agent@sha256:89189b6c9cf67ac6a9b137fa7427990ca5535077e53e729a0ff4635053e6970d",  # ab974fd8
    # #1398 branch history only (AW v0.2.0 omni, before #1418 made toolchain the default).
    "ghcr.io/agentparadise/agentic-workspace-omni-agent@sha256:12e7dc55d7aad558798552f2f373ddc0aebd3205e5b30543ff8751a2a12a0189",  # #1398
    "ghcr.io/agentparadise/agentic-workspace-toolchain@sha256:27b70b32a41b010f71291dc1ff8edd57fce8025ff19322bd9c6fa8aa92419dd8",  # f1647f93
    "ghcr.io/agentparadise/agentic-workspace-toolchain@sha256:e38b1a45b14e7b58040d7664a83e9f53191f24d9ea92462b4eeee829d3ad65f9",  # 70ca5fae
)
