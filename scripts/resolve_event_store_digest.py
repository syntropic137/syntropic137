"""Resolve the event-store image for the ESP commit this repo vendors (#1515).

WHY THIS EXISTS. syn137 does not build the event-store image; ESP publishes it
and the release pins a digest into the compose file every self-host pulls. The
release used to look up `event-store:<syn137 version>`. ESP tags its images with
ESP's OWN version, the two lines are independent, so that lookup could never
match: a warning fired on every release and the `latest` fallback was the only
path that ever ran. What users got was "whatever `latest` pointed at during the
release job", a race against another repository's publish schedule rather than
a stated dependency.

WHAT IT DOES INSTEAD. The `lib/event-sourcing-platform` gitlink is the stated
dependency. This reads ESP's version at that exact commit (root `package.json`,
which ESP's `scripts/bump_version.py` names as its source of truth), looks up
`event-store:v<version>` (ESP's release workflow tags the image with the GitHub
release tag, `v`-prefixed), and FAILS when that tag is not published. There is
no fallback: an unpublished ESP version means ESP must release first.

WHAT IT DOES NOT PROVE. A version, not a commit. ESP bumps its version in a
release PR, so a gitlink on ESP `main` some commits past a release tag carries
the same version as that tag and resolves to its image. That is the contract
option 2 of #1515 chose: image and source agree on the version by construction.

Used two ways:

    resolve_event_store_digest.py              # gate: preflight / PR CI
    resolve_event_store_digest.py --out FILE   # release: write the digest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

IMAGE = "ghcr.io/syntropic137/event-store"
SUBMODULE_PATH = "lib/event-sourcing-platform"
#: ESP's version source of truth, per its scripts/bump_version.py.
VERSION_FILE = "package.json"

#: The platforms the compose file is published for. An index missing either
#: gives that architecture `exec format error` at `docker compose up` (#1519).
REQUIRED_ARCHES = ("amd64", "arm64")
INDEX_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    }
)

_TIMEOUT_SECONDS = 120
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ResolveError(RuntimeError):
    """The event-store pin could not be established. Always fatal."""


@dataclass(frozen=True)
class LookupResult:
    """The outcome of one `imagetools inspect`, already classified.

    Exactly one of `digest` / `absent` / `error` is meaningful. An absent tag
    and a failed lookup are kept apart on purpose: collapsing them is how an
    auth failure once read as "version not found" and fell through to `latest`.
    """

    digest: str | None = None
    absent: bool = False
    error: str | None = None


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # A missing binary or a hung registry is a failed lookup, never "absent".
        msg = f"could not run {' '.join(cmd[:3])}: {exc}"
        raise ResolveError(msg) from exc


def submodule_gitlink(path: str = SUBMODULE_PATH) -> str:
    """The commit this repo ships for `path`, from the gitlink in HEAD.

    Not the submodule's checked-out HEAD: a working tree can sit anywhere, the
    gitlink is what the repo actually vendors.
    """
    result = _run(["git", "ls-tree", "HEAD", path])
    fields = result.stdout.split()
    if result.returncode != 0 or len(fields) < 3 or fields[1] != "commit":
        msg = f"could not read the gitlink for {path}: {(result.stderr or result.stdout).strip()[:200]}"
        raise ResolveError(msg)
    return fields[2]


def parse_esp_version(package_json: str) -> str:
    """ESP's version from the text of its root package.json."""
    try:
        doc = json.loads(package_json)
    except json.JSONDecodeError as exc:
        msg = f"ESP {VERSION_FILE} is not valid JSON: {exc}"
        raise ResolveError(msg) from exc
    version = doc.get("version") if isinstance(doc, dict) else None
    if not isinstance(version, str) or not _SEMVER_RE.match(version):
        msg = f"ESP {VERSION_FILE} has no usable semver 'version': {version!r}"
        raise ResolveError(msg)
    return version


def esp_version_at(gitlink: str, path: str = SUBMODULE_PATH) -> str:
    """ESP's version at exactly `gitlink`, read from the submodule's objects."""
    result = _run(["git", "-C", path, "show", f"{gitlink}:{VERSION_FILE}"])
    if result.returncode != 0:
        msg = (
            f"could not read {VERSION_FILE} at {gitlink} in {path}. "
            f"Is the submodule initialised? (git submodule update --init {path})\n"
            f"{result.stderr.strip()[:300]}"
        )
        raise ResolveError(msg)
    return parse_esp_version(result.stdout)


def image_tag(version: str) -> str:
    """ESP tags the image with its GitHub release tag, which is `v<version>`."""
    return f"v{version}"


def classify_lookup(ref: str, returncode: int, stdout: str, stderr: str = "") -> LookupResult:
    """Classify one `imagetools inspect --format {{.Manifest.Digest}}` run.

    On success only stdout is the answer: buildx may write warnings to stderr,
    and those must not turn a valid digest into a "malformed" one.

    On failure, "absent" requires the WHOLE diagnostic to be exactly
    `ERROR: <ref>: not found` (what buildx emits for a missing tag, measured
    against GHCR). A keyword search, or a line match inside a longer
    diagnostic, would let any failure that also mentions "not found" read as
    an absent tag. If buildx rewords this, the lookup fails loudly instead of
    guessing.
    """
    if returncode == 0:
        digest = stdout.strip()
        if not _DIGEST_RE.match(digest):
            return LookupResult(error=f"{ref} resolved to a malformed digest: {digest!r}")
        return LookupResult(digest=digest)
    diagnostic = (stdout + stderr).strip()
    if diagnostic == f"ERROR: {ref}: not found":
        return LookupResult(absent=True)
    return LookupResult(
        error=f"looking up {ref} failed, and NOT because it is missing:\n{diagnostic[:400]}"
    )


def lookup_index_digest(ref: str) -> LookupResult:
    """The digest the tag points at: the INDEX for a multi-arch image.

    Never `docker manifest inspect --verbose`: it returns one entry per
    platform, each carrying that platform's CHILD digest (#1519).
    """
    result = _run(
        ["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{.Manifest.Digest}}"]
    )
    return classify_lookup(ref, result.returncode, result.stdout, result.stderr)


def verify_index(digest: str, raw_manifest: str) -> None:
    """Fail unless `raw_manifest` is an index covering every required arch."""
    try:
        doc = json.loads(raw_manifest)
    except json.JSONDecodeError as exc:
        msg = f"event-store {digest}: raw manifest is not JSON: {exc}"
        raise ResolveError(msg) from exc
    if not isinstance(doc, dict):
        msg = f"event-store {digest}: raw manifest is not an object"
        raise ResolveError(msg)
    media_type = doc.get("mediaType")
    if media_type not in INDEX_MEDIA_TYPES:
        msg = (
            f"event-store {digest} is {media_type!r}, not a manifest index. A single-platform "
            "digest breaks every self-host on another architecture (#1519)."
        )
        raise ResolveError(msg)
    manifests = doc.get("manifests")
    present: set[str] = set()
    if isinstance(manifests, list):
        for entry in manifests:
            platform = entry.get("platform") if isinstance(entry, dict) else None
            if isinstance(platform, dict) and platform.get("os") == "linux":
                arch = platform.get("architecture")
                if isinstance(arch, str):
                    present.add(arch)
    missing = [a for a in REQUIRED_ARCHES if a not in present]
    if missing:
        msg = (
            f"event-store index {digest} has no linux/{', linux/'.join(missing)} manifest (#1519)."
        )
        raise ResolveError(msg)


def resolve(gitlink: str, version: str, lookup: LookupResult) -> str:
    """The verdict on one lookup. Pure, so the no-fallback rule is testable."""
    ref = f"{IMAGE}:{image_tag(version)}"
    if lookup.error is not None:
        raise ResolveError(lookup.error)
    if lookup.absent or lookup.digest is None:
        msg = (
            f"{ref} is not published.\n"
            f"  {SUBMODULE_PATH} is pinned at {gitlink}, which declares ESP {version}.\n"
            "  The release refuses to pin any other event-store image (#1515): ESP must\n"
            "  publish this version first, or the gitlink must move to a released commit."
        )
        raise ResolveError(msg)
    return lookup.digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, help="write the resolved index digest to this file")
    args = parser.parse_args(argv)

    try:
        gitlink = submodule_gitlink()
        version = esp_version_at(gitlink)
        ref = f"{IMAGE}:{image_tag(version)}"
        digest = resolve(gitlink, version, lookup_index_digest(ref))
        raw = _run(["docker", "buildx", "imagetools", "inspect", f"{IMAGE}@{digest}", "--raw"])
        if raw.returncode != 0:
            msg = f"could not fetch the raw manifest for {IMAGE}@{digest}:\n{raw.stderr.strip()[:400]}"
            raise ResolveError(msg)
        verify_index(digest, raw.stdout)
    except ResolveError as exc:
        # Under Actions, one annotation with encoded newlines; locally, plain text.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::error::{exc}".replace("\n", "%0A"), file=sys.stderr)
        else:
            print(f"event-store pin FAILED: {exc}", file=sys.stderr)
        return 1

    print(
        f"event-store {image_tag(version)} (ESP {gitlink[:12]}) -> {digest} "
        f"(linux/{' + linux/'.join(REQUIRED_ARCHES)} verified)"
    )
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(f"{digest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
