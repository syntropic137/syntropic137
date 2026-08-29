"""Every pinned workspace image must come from the protected release channel.

WHY THIS EXISTS. On 2026-08-29 the default workspace image was pinned to a
digest whose own OCI labels said:

    agentic.image.channel             = edge
    org.opencontainers.image.version  = edge

So the image every agent ran was an unreviewed `main` build, bypassing the
documented chain: merge -> image build -> protected `release` -> a
`PINNED_DIGESTS` bump. It went unnoticed for weeks.

WHY COSIGN DID NOT CATCH IT. Signature verification accepts identities from
both `main` and `release`. It proves an image was built by our CI, not that it
was approved for release. Provenance is not approval.

WHY THE EXISTING GATE DID NOT CATCH IT. `check-default-workspace-image` probes
only `DEFAULT_WORKSPACE_IMAGE`. `CLAUDE_CLI` was pinned to a stale digest from
an older release tree and nothing looked at it, so it drifted silently and
disagreed with the submodule it shipped alongside.

This checks EVERY entry in `PINNED_DIGESTS`, because the one nobody checks is
the one that drifts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass

#: The label a release build stamps. Asserting this is far simpler and more
#: direct than reasoning about cosign signing identities, and it is the field
#: that was already telling the truth while everything else looked fine.
CHANNEL_LABEL = "agentic.image.channel"
REQUIRED_CHANNEL = "release"

#: A registry that never answers must not hang CI forever.
_INSPECT_TIMEOUT_SECONDS = 120

#: Every release build stamps the commit it was built from. All pins should come
#: from the SAME build, because they ship alongside one submodule pointer.
REVISION_LABEL = "org.opencontainers.image.revision"


@dataclass(frozen=True)
class ImageChannel:
    """What an image says about itself."""

    provider: str
    ref: str
    channel: str | None
    revision: str | None
    platforms: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.channel == REQUIRED_CHANNEL


class MultiPlatformDisagreement(RuntimeError):
    """Platforms of one image disagree about channel or revision."""


def platform_labels(image_config: object) -> dict[str, dict[str, str]]:
    """`{platform: {label: value}}` from a buildx `.Image` document.

    The document is keyed BY PLATFORM at the top level:

        {"linux/amd64": {"config": {"Labels": {...}}}, "linux/arm64": {...}}

    The first version of this walked the structure looking for anything that
    smelled like a label map and returned the FIRST hit. On a multi-arch image
    that reads one arbitrary platform: amd64 could say `release` while arm64
    said `edge` and the gate would pass, and channel and revision could even be
    read from different platforms. A gate whose entire purpose is catching a
    silent mismatch cannot itself resolve ambiguity by picking one.
    """
    if not isinstance(image_config, dict) or not image_config:
        msg = f"unrecognised imagetools output: {type(image_config).__name__}"
        raise RuntimeError(msg)

    out: dict[str, dict[str, str]] = {}
    for platform, entry in image_config.items():
        config = entry.get("config") if isinstance(entry, dict) else None
        raw = config.get("Labels") if isinstance(config, dict) else None
        labels = raw if isinstance(raw, dict) else {}
        out[str(platform)] = {k: v for k, v in labels.items() if isinstance(v, str)}
    return out


def agreed_label(labels_by_platform: dict[str, dict[str, str]], label: str) -> str | None:
    """The value every platform agrees on, or raise if they disagree.

    Disagreement is a hard error rather than a `None`: `None` would flow into
    the ordinary "missing label" path and read as a pin that simply lacks
    provenance, when in fact it is a pin whose architectures were built from
    different sources - strictly worse and worth its own message.
    """
    seen = {platform: labels.get(label) for platform, labels in labels_by_platform.items()}
    distinct = set(seen.values())
    if len(distinct) > 1:
        detail = ", ".join(f"{p}={v or '<none>'}" for p, v in sorted(seen.items()))
        msg = f"platforms disagree on {label}: {detail}"
        raise MultiPlatformDisagreement(msg)
    return distinct.pop() if distinct else None


#: The submodule whose source builds these images. The pins ship alongside this
#: exact commit, so the build they came from must BE this commit.
SUBMODULE_PATH = "lib/agentic-primitives"


def submodule_gitlink(path: str = SUBMODULE_PATH) -> str:
    """The commit this repo vendors for `path`.

    Read from the gitlink rather than the submodule's own checked-out HEAD:
    a working tree can sit on any commit, but the gitlink is what the repo
    actually ships, and it is what CI would clone.
    """
    result = subprocess.run(
        ["git", "ls-tree", "HEAD", path],
        capture_output=True,
        text=True,
        check=False,
        timeout=_INSPECT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or not result.stdout.strip():
        msg = f"could not read the gitlink for {path}: {result.stderr.strip()[:200]}"
        raise RuntimeError(msg)
    # "160000 commit <sha>\t<path>"
    fields = result.stdout.split()
    if len(fields) < 3 or fields[1] != "commit":
        msg = f"{path} is not a submodule gitlink: {result.stdout.strip()[:120]}"
        raise RuntimeError(msg)
    return fields[2]


def inspect_channel(provider: str, ref: str) -> ImageChannel:
    """Read one image's channel label from the registry."""
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{json .Image}}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_INSPECT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        # An unreachable registry must not read as "no label, therefore fine".
        msg = f"{provider}: could not inspect {ref}\n{result.stderr.strip()[:400]}"
        raise RuntimeError(msg)
    config = json.loads(result.stdout)
    by_platform = platform_labels(config)
    return ImageChannel(
        provider,
        ref,
        agreed_label(by_platform, CHANNEL_LABEL),
        agreed_label(by_platform, REVISION_LABEL),
        platforms=tuple(sorted(by_platform)),
    )


def evaluate(results: list[ImageChannel], gitlink: str) -> tuple[int, list[str]]:
    """The verdict over already-inspected pins. Pure, so it is testable.

    Extracted after a codex review found none of this file's tests reached the
    invariants at all: every case exercised a helper, so deleting invariant 2
    or 3 outright left the whole suite green. A gate against silent passes had
    a silent pass in its own test suite.
    """
    lines: list[str] = []
    for r in results:
        mark = "OK " if r.ok else "BAD"
        rev = (r.revision or "<none>")[:12]
        lines.append(
            f"  [{mark}] {r.provider:<12} channel={r.channel or '<none>':<8} revision={rev}"
        )

    # FIRST: every pin came through the protected release chain.
    bad = [r for r in results if not r.ok]
    if bad:
        lines.append("")
        lines.append(f"{len(bad)} pinned image(s) are not from the '{REQUIRED_CHANNEL}' channel.")
        lines.append("A pin must come from the protected release build, not from main/edge:")
        lines.append("  merge -> image build -> release branch -> bump PINNED_DIGESTS")
        lines.extend(f"  {r.provider}: {r.ref}" for r in bad)
        return 1, lines

    # SECOND: all pins share one source revision.
    #
    # Catches staleness, which the channel check cannot: CLAUDE_CLI sat on a
    # digest from an OLDER release tree - correctly signed, correctly
    # release-channel, and disagreeing with the submodule it shipped beside.
    #
    # Note this compares SOURCE REVISIONS, not build runs. Two rebuilds of one
    # commit produce different bytes and pass; that is deliberate, since the
    # question here is which source the images came from.
    revisions = {r.revision for r in results if r.revision}
    if len(revisions) > 1:
        lines.append("")
        lines.append("Pinned images come from DIFFERENT source revisions, so one is stale:")
        lines.extend(f"  {r.provider}: revision {r.revision or '<none>'}" for r in results)
        lines.append("")
        lines.append("They ship alongside a single submodule pointer, so a pin from an")
        lines.append("older build can disagree with the code it runs beside. Re-pin every")
        lines.append("entry from the same release build.")
        return 1, lines

    # THIRD: that revision is the submodule we vendor.
    #
    # THIS IS OUR POLICY, NOT AN UPSTREAM CONTRACT. A codex review checked the
    # upstream workflow: agentic-primitives documents `agentic.image.channel`,
    # but nothing upstream promises that `org.opencontainers.image.revision`
    # equals a consumer's gitlink - the label comes from docker/metadata-action's
    # implicit default rather than an explicit stamp. It is true today and we
    # want it enforced, so it is enforced here and named as a coupling we chose.
    # Formalising it upstream is #985.
    revision = revisions.pop() if revisions else None
    if revision != gitlink:
        lines.append("")
        lines.append("Pinned images were NOT built from the submodule this repo ships:")
        lines.append(f"  images   built from {revision or '<none>'}")
        lines.append(f"  {SUBMODULE_PATH} pinned at {gitlink}")
        lines.append("")
        lines.append("Agents would run one commit while the API imports another.")
        lines.append("Re-pin from the release build of the commit in the gitlink.")
        return 1, lines

    lines.append(
        f"All {len(results)} pinned workspace image(s) are release-channel, "
        f"built from {revision[:12] if revision else '<unknown>'}, "
        f"matching the {SUBMODULE_PATH} gitlink."
    )
    return 0, lines


def main() -> int:
    from syn_shared.settings.workspace_images import (
        PINNED_DIGESTS,
        WorkspaceImageProvider,
        workspace_image_ref,
    )

    if not PINNED_DIGESTS:
        print("PINNED_DIGESTS is empty; nothing to check. Failing closed.", file=sys.stderr)
        return 1

    # A gate that checks the pins it is GIVEN says nothing about the pins that
    # were never added. One correct entry satisfies all three invariants
    # vacuously, so a provider dropped from the map would pass silently -
    # the same "nobody looks at it" shape that let CLAUDE_CLI drift.
    missing = [p.name for p in WorkspaceImageProvider if p not in PINNED_DIGESTS]
    if missing:
        print(f"providers with no pinned digest: {', '.join(missing)}", file=sys.stderr)
        print("Every provider must be pinned, or it is not covered by this gate.", file=sys.stderr)
        return 1

    results = [
        inspect_channel(provider.name, workspace_image_ref(provider)) for provider in PINNED_DIGESTS
    ]
    code, lines = evaluate(results, submodule_gitlink())
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
