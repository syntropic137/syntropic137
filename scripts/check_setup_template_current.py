"""The published ``@syntropic137/setup`` template must pin a given release (#1863).

WHY THIS EXISTS. ``npx @syntropic137/setup`` installs from the compose template
inside the npm package, not from the GitHub release. The template-sync bot
copies the release's compose asset into the setup repo, which is then published
to npm. If that hop is skipped or stale, new installs pull an older release's
images while every release check stays green, because nothing compared the two.

The expected side is the ``docker-compose.syntropic137.yaml`` asset of a GitHub
release. The release workflow (release-containers.yaml, "Pin image digests in
compose file") writes its ``# Pinned to release vX.Y.Z`` header and swaps each
``ghcr.io/syntropic137/*`` tag for an ``@sha256:`` digest. The found side is
``package/templates/docker-compose.syntropic137.yaml`` in the npm tarball, the
path ``npm pack --dry-run @syntropic137/setup`` lists.

Two templates agree when they name the same release and pin the same digest
(and tag, where there is one) for every ``ghcr.io/syntropic137`` image. Other
registries' images are not ours to pin and are ignored.

Exit codes: 0 the template matches, 1 it does not (a per-image table is
printed), 2 a fetch or parse error.

Usage: uv run python scripts/check_setup_template_current.py
           [--release vX.Y.Z] [--setup-version X.Y.Z]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO = "syntropic137/syntropic137"
PACKAGE = "@syntropic137/setup"
#: The release asset, and the template's path inside the npm tarball.
COMPOSE_ASSET = "docker-compose.syntropic137.yaml"
TARBALL_TEMPLATE = f"package/templates/{COMPOSE_ASSET}"

_VERSION = r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?"
_RELEASE_ARG = re.compile(rf"^{_VERSION}$")
_HEADER_PREFIX = "# Pinned to release"
_HEADER = re.compile(rf"^{_HEADER_PREFIX} ({_VERSION})(?:\s|$)")
#: ``name@sha256:`` and ``name:tag@sha256:`` (the minio mirror carries its tag).
_PINNED_REF = re.compile(
    r"ghcr\.io/syntropic137/(?P<name>[a-z0-9][a-z0-9._-]*)"
    r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]*))?"
    r"@(?P<digest>sha256:[0-9a-f]{64})"
)

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_ERROR = 2


class TemplateParseError(Exception):
    """A compose template is not a pinned release template."""


class FetchError(Exception):
    """A release asset or npm package could not be fetched or read."""


@dataclass(frozen=True)
class PinnedTemplate:
    """What a pinned compose template commits to."""

    release: str
    #: image name -> ``[tag]@sha256:digest``
    images: Mapping[str, str]


@dataclass(frozen=True)
class Mismatch:
    """One subject on which the two templates disagree; ``None`` is absent."""

    subject: str
    expected: str | None
    found: str | None


def parse_template(text: str, source: str) -> PinnedTemplate:
    """Read the release header and every pinned ``ghcr.io/syntropic137`` image."""
    headers = [line for line in text.splitlines() if line.startswith(_HEADER_PREFIX)]
    if len(headers) != 1:
        raise TemplateParseError(
            f"{source}: expected one '{_HEADER_PREFIX} vX.Y.Z' line, found {len(headers)}"
        )
    header = _HEADER.match(headers[0])
    if header is None:
        raise TemplateParseError(f"{source}: malformed release header: {headers[0]!r}")

    images: dict[str, str] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for ref in _PINNED_REF.finditer(line):
            name, tag = ref["name"], ref["tag"]
            pin = f"{tag}@{ref['digest']}" if tag else ref["digest"]
            # The same image under several services is one pin; two pins for one
            # image would make "the" expected digest a guess.
            if images.setdefault(name, pin) != pin:
                raise TemplateParseError(
                    f"{source}: ghcr.io/syntropic137/{name} is pinned twice: "
                    f"{images[name]} and {pin}"
                )
    if not images:
        raise TemplateParseError(f"{source}: no ghcr.io/syntropic137/*@sha256: image refs")
    return PinnedTemplate(release=header[1], images=images)


def compare(expected: PinnedTemplate, found: PinnedTemplate) -> list[Mismatch]:
    """Every disagreement between two templates; empty when they match."""
    mismatches: list[Mismatch] = []
    if expected.release != found.release:
        mismatches.append(Mismatch("release header", expected.release, found.release))
    for name in sorted(expected.images.keys() | found.images.keys()):
        want, got = expected.images.get(name), found.images.get(name)
        if want != got:
            mismatches.append(Mismatch(name, want, got))
    return mismatches


def format_mismatches(mismatches: list[Mismatch]) -> str:
    rows = [("IMAGE", "EXPECTED (release)", "FOUND (setup template)")]
    rows += [(m.subject, m.expected or "(missing)", m.found or "(missing)") for m in mismatches]
    widths = [max(len(row[i]) for row in rows) for i in range(2)]
    return "\n".join(f"  {row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]}" for row in rows)


# --- fetching (gh, npm) -------------------------------------------------------


class _NpmPackEntry(BaseModel):
    """The part of one ``npm pack --json`` entry this script reads."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    version: str
    filename: str


def _run(command: list[str], cwd: Path, env: Mapping[str, str] | None = None) -> str:
    try:
        done = subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        raise FetchError(f"'{command[0]}' is not installed or not on PATH") from exc
    if done.returncode != 0:
        raise FetchError(f"'{' '.join(command)}' exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def latest_release(workdir: Path) -> str:
    return _run(
        ["gh", "release", "view", "--repo", REPO, "--json", "tagName", "--jq", ".tagName"],
        workdir,
    ).strip()


def fetch_release_template(release: str, workdir: Path) -> str:
    dest = workdir / "release"
    dest.mkdir()
    _run(
        ["gh", "release", "download", release, "--repo", REPO,
         "--pattern", COMPOSE_ASSET, "--dir", str(dest)],
        workdir,
    )  # fmt: skip
    return (dest / COMPOSE_ASSET).read_text()


def fetch_setup_template(setup_version: str, workdir: Path) -> tuple[str, str]:
    """The template inside the npm tarball, and the version npm resolved."""
    dest = workdir / "npm"
    dest.mkdir()
    # A private cache keeps a small or read-only $HOME out of the way.
    env = {**os.environ, "npm_config_cache": str(workdir / "npm-cache")}
    out = _run(
        ["npm", "pack", f"{PACKAGE}@{setup_version}", "--json", "--pack-destination", str(dest)],
        workdir,
        env,
    )
    try:
        entries = TypeAdapter(list[_NpmPackEntry]).validate_json(out)
    except ValidationError as exc:
        raise FetchError(f"unreadable 'npm pack --json' output for {PACKAGE}") from exc
    if len(entries) != 1:
        raise FetchError(f"'npm pack' produced {len(entries)} tarballs for {PACKAGE}, not 1")
    tarball = dest / entries[0].filename
    try:
        with tarfile.open(tarball) as archive:
            member = archive.extractfile(TARBALL_TEMPLATE)
            if member is None:
                raise FetchError(f"{TARBALL_TEMPLATE} in {tarball.name} is not a file")
            return member.read().decode(), entries[0].version
    except (KeyError, tarfile.TarError) as exc:
        raise FetchError(f"{tarball.name} has no readable {TARBALL_TEMPLATE}") from exc


def _release_arg(value: str) -> str:
    if not _RELEASE_ARG.match(value):
        raise argparse.ArgumentTypeError(f"not a release tag like v1.2.3: {value!r}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release", type=_release_arg, help="default: the latest release")
    parser.add_argument("--setup-version", default="latest", help="default: npm's latest")
    args = parser.parse_args(argv)

    try:
        with tempfile.TemporaryDirectory(prefix="setup-template-") as tmp:
            workdir = Path(tmp)
            release: str = args.release or latest_release(workdir)
            expected = parse_template(
                fetch_release_template(release, workdir), f"release {release} {COMPOSE_ASSET}"
            )
            text, setup_version = fetch_setup_template(args.setup_version, workdir)
            found = parse_template(text, f"{PACKAGE}@{setup_version} {TARBALL_TEMPLATE}")
    except (FetchError, TemplateParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    mismatches = compare(expected, found)
    if mismatches:
        print(f"FAIL: {PACKAGE}@{setup_version} is not pinned to release {release}:")
        print(format_mismatches(mismatches))
        return EXIT_MISMATCH
    print(
        f"OK: {PACKAGE}@{setup_version} pins release {release} "
        f"({len(expected.images)} ghcr.io/syntropic137 images)"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
