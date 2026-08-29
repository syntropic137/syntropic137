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

    @property
    def ok(self) -> bool:
        return self.channel == REQUIRED_CHANNEL


def find_label(image_config: object, label: str) -> str | None:
    """Pull one label out of an image config, wherever it is nested.

    Buildx nests labels differently across manifest shapes, so this walks
    rather than indexing a fixed path -- a KeyError here would read as "no
    label" and pass the gate, which is the failure mode being prevented.
    """
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if "label" in key.lower() and isinstance(value, dict):
                    got = value.get(label)
                    if isinstance(got, str):
                        found.append(got)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(image_config)
    return found[0] if found else None


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
    )
    if result.returncode != 0:
        # An unreachable registry must not read as "no label, therefore fine".
        msg = f"{provider}: could not inspect {ref}\n{result.stderr.strip()[:400]}"
        raise RuntimeError(msg)
    config = json.loads(result.stdout)
    return ImageChannel(
        provider,
        ref,
        find_label(config, CHANNEL_LABEL),
        find_label(config, REVISION_LABEL),
    )


def main() -> int:
    from syn_shared.settings.workspace_images import PINNED_DIGESTS, workspace_image_ref

    if not PINNED_DIGESTS:
        print("PINNED_DIGESTS is empty; nothing to check. Failing closed.", file=sys.stderr)
        return 1

    results = [
        inspect_channel(provider.name, workspace_image_ref(provider)) for provider in PINNED_DIGESTS
    ]

    for r in results:
        mark = "OK " if r.ok else "BAD"
        rev = (r.revision or "<none>")[:12]
        print(f"  [{mark}] {r.provider:<12} channel={r.channel or '<none>':<8} revision={rev}")

    bad = [r for r in results if not r.ok]
    if bad:
        print()
        print(f"{len(bad)} pinned image(s) are not from the '{REQUIRED_CHANNEL}' channel.")
        print("A pin must come from the protected release build, not from main/edge:")
        print("  merge -> image build -> release branch -> bump PINNED_DIGESTS")
        for r in bad:
            print(f"  {r.provider}: {r.ref}")
        return 1

    # SECOND INVARIANT: all pins must come from the SAME release build.
    #
    # This is the one that catches staleness, which the channel check cannot.
    # CLAUDE_CLI sat on a digest from an OLDER release tree - correctly signed,
    # correctly release-channel, and disagreeing with the submodule it shipped
    # beside. Nothing looked at it because the only gate probed the default
    # image. Pins ship together, so they must be built together.
    revisions = {r.revision for r in results if r.revision}
    if len(revisions) > 1:
        print()
        print("Pinned images come from DIFFERENT builds, so at least one is stale:")
        for r in results:
            print(f"  {r.provider}: revision {r.revision or '<none>'}")
        print()
        print("They ship alongside a single submodule pointer, so a pin from an")
        print("older build can disagree with the code it runs beside. Re-pin every")
        print("entry from the same release build.")
        return 1

    # THIRD INVARIANT: that single build must be the submodule we vendor.
    #
    # Raised by a codex review of #941: the first two invariants are satisfied
    # by any self-consistent set of pins, including a set that agrees with
    # itself and disagrees with the source in lib/. The images carry the
    # workspace toolchain while the gitlink carries the Python we import from
    # it, so a mismatch means agents run one commit and the API imports another.
    revision = revisions.pop() if revisions else None
    gitlink = submodule_gitlink()
    if revision != gitlink:
        print()
        print("Pinned images were NOT built from the submodule this repo ships:")
        print(f"  images   built from {revision or '<none>'}")
        print(f"  {SUBMODULE_PATH} pinned at {gitlink}")
        print()
        print("Agents would run one commit while the API imports another.")
        print("Re-pin from the release build of the commit in the gitlink.")
        return 1

    print(
        f"All {len(results)} pinned workspace image(s) are release-channel, "
        f"built from {revision[:12] if revision else '<unknown>'}, "
        f"matching the {SUBMODULE_PATH} gitlink."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
