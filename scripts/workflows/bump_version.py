#!/usr/bin/env python3
"""Bump the product version across every file that carries it.

Usage:
    python scripts/workflows/bump_version.py 0.20.0          # Write the new version everywhere
    python scripts/workflows/bump_version.py --check          # Validate every file agrees
    python scripts/workflows/bump_version.py --current        # Print current version
    python scripts/workflows/bump_version.py --check-release  # Validate version is bumped vs release branch

Covered: the Python manifest of every uv workspace member, the Node manifests
we version in lockstep, the three plugin schema `$id` values, and uv.lock.
Submodules (event-sourcing-platform, agentic-primitives) and
packages/openclaw-plugin have independent versioning and are never touched.

All files are pre-validated before any writes occur. If the target version is
malformed, or any covered file is missing a version field, the script fails
without modifying anything.

─────────────────────────────────────────────────────────────────────────────
CI DEPENDENCY - this script is called directly by the release gate workflow:
  .github/workflows/_check-version.yml
    → python3 scripts/workflows/bump_version.py --check          (every file agrees)
    → python3 scripts/workflows/bump_version.py --check-release  (version > release branch)

That workflow checks out without submodules, so nothing here may read lib/.
Also called by the just recipes `check-version` and `bump-version`.
Do not rename flags or change exit codes without updating the workflow.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # scripts/workflows/ -> scripts/ -> repo root

# Everything below is RELATIVE and resolved against ROOT at call time. Absolute
# constants baked at import cannot be redirected by monkeypatching ROOT, which
# is how the tests isolate the filesystem - an earlier revision of this file had
# them and `bump()` escaped its tmpdir into the real repo.

# Node packages versioned in lockstep with the product. Unlike the Python
# members below there is no glob to derive this from: pnpm-workspace.yaml lists
# packages/openclaw-plugin too, and that one is independently versioned (0.1.0).
# `TestNodeManifestList` fails if this list and pnpm-workspace.yaml disagree.
PACKAGE_JSON_RELPATHS = (
    "apps/syn-cli-node/package.json",
    "apps/syn-dashboard-ui/package.json",
    "apps/syn-docs/package.json",
)

# The plugin schemas advertise the version in their `$id`. `--check` reporting
# "OK: All 11 files" while these were stale is how a build shipped schemas
# announcing the previous version (see the v0.28.0-beta.9 bump).
SCHEMA_RELPATHS = (
    "schemas/plugin/workflow.schema.json",
    "schemas/plugin/triggers.schema.json",
    "schemas/plugin/phase-frontmatter.schema.json",
)

LOCKFILE_RELPATH = "uv.lock"


@dataclass(frozen=True)
class OwnedPackage:
    """A Python package whose version this repo owns.

    `relpath` is the workspace-relative directory, spelled the way uv records
    it in uv.lock's `source` table ("." for the workspace root).
    """

    relpath: str
    pyproject: Path


def owned_packages() -> list[OwnedPackage]:
    """Every Python package this repo versions in lockstep with the product.

    Derived from `[tool.uv.workspace]` in the root pyproject.toml - the same
    members/exclude globs uv itself resolves - plus the workspace root. A
    package added under apps/ or packages/ is therefore bumped and checked from
    the day it is added, with no list to keep in sync. Independently versioned
    packages are already outside those globs: the submodules live under lib/,
    and openclaw-plugin / the Node apps are in `exclude`.
    """
    root_pyproject = ROOT / "pyproject.toml"
    workspace = (
        tomllib.loads(root_pyproject.read_text()).get("tool", {}).get("uv", {}).get("workspace", {})
    )
    excluded = {d for pattern in workspace.get("exclude", []) for d in ROOT.glob(pattern)}

    found = [OwnedPackage(".", root_pyproject)]
    for pattern in workspace.get("members", []):
        for directory in sorted(ROOT.glob(pattern)):
            pyproject = directory / "pyproject.toml"
            if directory in excluded or not pyproject.is_file():
                continue
            found.append(OwnedPackage(directory.relative_to(ROOT).as_posix(), pyproject))
    return found


def package_json_files() -> list[Path]:
    return [ROOT / rel for rel in PACKAGE_JSON_RELPATHS]


def schema_files() -> list[Path]:
    return [ROOT / rel for rel in SCHEMA_RELPATHS]


def lockfile() -> Path:
    return ROOT / LOCKFILE_RELPATH


SCHEMA_ID_RE = re.compile(r"(/schemas/plugin/v)[^/]+(/)")

PYPROJECT_VERSION_RE = re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE)
PACKAGE_JSON_VERSION_RE = re.compile(r'^(\s*"version"\s*:\s*")[^"]*(")', re.MULTILINE)

# A uv.lock record for a workspace member. Registry dependencies use
# `source = { registry = ... }` and are not matched.
LOCK_WORKSPACE_SOURCE_RE = re.compile(
    r'^source = \{ (?:editable|virtual) = "([^"]+)" \}', re.MULTILINE
)

# The version forms this repository ships. DELIBERATELY NARROWER THAN SEMVER.
#
# `just bump-version` writes the manifests, regenerates uv.lock, then runs
# `--check`. uv canonicalises PEP 440 far more broadly than `to_pep440` below,
# so any form the two disagree on would be accepted here and then leave the
# repo permanently stale to its own gate. Measured against uv 0.11.8:
#
#   0.29.0-beta.09  uv writes 0.29.0b9    (zero-padding dropped)
#   0.29.0-beta1    uv writes 0.29.0b1    (separator optional)
#   0.29.0-alpha    uv writes 0.29.0a0    (number implied)
#   0.29.0-dev.1    uv writes 0.29.0.dev1 (a different release segment)
#   0.29.0-rc.1.2   uv refuses to parse the manifest at all
#
# Rejecting them is not a loss: every tag this project has ever cut is either
# X.Y.Z or X.Y.Z-beta.N. alpha and rc are permitted for symmetry.
VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta|rc)\.(0|[1-9]\d*))?$"
)

VERSION_SYNTAX = "X.Y.Z or X.Y.Z-{alpha,beta,rc}.N (e.g. 0.29.0, 0.29.0-beta.1)"

# Ordering of the prerelease tags, and the letters uv abbreviates them to.
_PRERELEASE_TAGS = {"alpha": (0, "a"), "beta": (1, "b"), "rc": (2, "rc")}


def read_pyproject_version(path: Path) -> str | None:
    text = path.read_text()
    m = re.search(r'^version\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return m.group(1) if m else None


def read_package_json_version(path: Path) -> str | None:
    data = json.loads(path.read_text())
    return data.get("version")


def to_pep440(version: str) -> str:
    """The spelling uv records in uv.lock (0.28.0-beta.9 -> 0.28.0b9).

    Exact for every form `VERSION_RE` accepts - which is the whole reason
    `VERSION_RE` is narrow. Raises ValueError on anything else rather than
    guessing, because a wrong guess here reads as "uv.lock is stale".
    """
    major, minor, patch, pre = parse_version(version)
    if pre is None:
        return f"{major}.{minor}.{patch}"
    tag, number = pre
    return f"{major}.{minor}.{patch}{_PRERELEASE_TAGS[tag][1]}{number}"


def read_schema_version(path: Path) -> str | None:
    m = re.search(r"/schemas/plugin/v([^/]+)/", path.read_text())
    return m.group(1) if m else None


@dataclass(frozen=True)
class LockRecord:
    name: str
    version: str
    relpath: str


def read_lockfile_records() -> dict[str, LockRecord]:
    """Every workspace member uv recorded in uv.lock, keyed by source path.

    Keyed by path rather than by name so ownership is decided by one rule -
    "is this directory a member of our workspace" - instead of by a second,
    hand-written list of names that can disagree with the first.
    """
    path = lockfile()
    if not path.exists():
        return {}
    found: dict[str, LockRecord] = {}
    for block in path.read_text().split("[[package]]"):
        nm = re.search(r'^name = "([^"]+)"', block, re.MULTILINE)
        vm = re.search(r'^version = "([^"]+)"', block, re.MULTILINE)
        sm = LOCK_WORKSPACE_SOURCE_RE.search(block)
        if nm and vm and sm:
            found[sm.group(1)] = LockRecord(nm.group(1), vm.group(1), sm.group(1))
    return found


def read_all_versions() -> dict[Path, str | None]:
    versions: dict[Path, str | None] = {}
    for pkg in owned_packages():
        versions[pkg.pyproject] = read_pyproject_version(pkg.pyproject)
    for p in package_json_files():
        versions[p] = read_package_json_version(p)
    return versions


def get_current_version() -> str:
    """Read version from root pyproject.toml (source of truth)."""
    v = read_pyproject_version(ROOT / "pyproject.toml")
    if not v:
        print("ERROR: Could not read version from root pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return v


def parse_version(v: str) -> tuple[int, int, int, tuple[str, int] | None]:
    """Split an accepted version into (major, minor, patch, prerelease).

    The prerelease is `(tag, number)` or None. Raises ValueError for anything
    outside the grammar `VERSION_RE` documents.
    """
    m = VERSION_RE.fullmatch(v)
    if not m:
        raise ValueError(f"Unsupported version {v!r}. Expected {VERSION_SYNTAX}")
    major, minor, patch, tag, number = m.groups()
    pre = (tag, int(number)) if tag else None
    return int(major), int(minor), int(patch), pre


def _sort_key(version: str) -> tuple[int, int, int, int, int, int]:
    major, minor, patch, pre = parse_version(version)
    # A stable release outranks every prerelease of the same core version, so
    # it sorts with a leading 1 and the prereleases with a leading 0.
    rank = (1, 0, 0) if pre is None else (0, _PRERELEASE_TAGS[pre[0]][0], pre[1])
    return (major, minor, patch, *rank)


def compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings. Returns -1, 0, or 1."""
    a, b = _sort_key(v1), _sort_key(v2)
    return (a > b) - (a < b)


def check_release_bump(release_ref: str = "origin/release") -> bool:
    """Validate current version is greater than what's on the release branch.

    Used by CI to ensure the PR has actually bumped the version before merging.
    Reads the release branch version via git show to avoid a full checkout.
    """
    pr_version = get_current_version()

    try:
        result = subprocess.run(
            ["git", "show", f"{release_ref}:pyproject.toml"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        print(f"ERROR: Could not read {release_ref}:pyproject.toml", file=sys.stderr)
        print("Ensure 'git fetch origin' has been run.", file=sys.stderr)
        return False

    m = re.search(r'^version\s*=\s*"([^"]*)"', result.stdout, re.MULTILINE)
    release_version: str | None = m.group(1) if m else None

    if release_version is None:
        print(f"ERROR: No version field found in {release_ref}:pyproject.toml", file=sys.stderr)
        return False

    print(f"PR version:      {pr_version}")
    print(f"Release version: {release_version}")

    if pr_version == release_version:
        print(
            f"ERROR: Version {pr_version} has not been bumped from the current release.",
            file=sys.stderr,
        )
        print("Run: just bump-version <new-version>", file=sys.stderr)
        return False

    try:
        cmp = compare_versions(pr_version, release_version)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return False

    if cmp <= 0:
        print(
            f"ERROR: PR version {pr_version} is not greater than release version {release_version}",
            file=sys.stderr,
        )
        return False

    print(f"OK: {pr_version} > {release_version}")
    return True


def check_consistency() -> bool:
    """Validate every version-carrying file agrees. Returns True if consistent."""
    versions = read_all_versions()
    unique = set(versions.values())

    if None in unique:
        missing = [str(p.relative_to(ROOT)) for p, v in versions.items() if v is None]
        print(f"ERROR: Could not read version from: {', '.join(missing)}", file=sys.stderr)
        return False

    if len(unique) != 1:
        print("ERROR: Version mismatch across manifests:", file=sys.stderr)
        for path, version in sorted(versions.items(), key=lambda x: str(x[0])):
            print(f"  {path.relative_to(ROOT)}: {version}", file=sys.stderr)
        return False

    version = unique.pop()
    try:
        expected_lock = to_pep440(version)
    except ValueError as exc:
        print(f"ERROR: root pyproject.toml carries an unsupported version. {exc}", file=sys.stderr)
        return False

    stale: list[str] = []

    # Schema $id values and uv.lock records carry the version too. This check
    # used to stop at the manifests and report OK while these were stale, which
    # is how a build shipped schemas advertising the previous version.
    for path in schema_files():
        got = read_schema_version(path)
        if got != version:
            stale.append(f"{path.relative_to(ROOT)}: {got} (expected {version})")

    records = read_lockfile_records()
    for pkg in owned_packages():
        record = records.get(pkg.relpath)
        if record is None:
            stale.append(f"uv.lock: no record for {pkg.relpath}")
        elif record.version != expected_lock:
            stale.append(f"uv.lock [{record.name}]: {record.version} (expected {expected_lock})")

    if stale:
        print("ERROR: manifests agree but derived files are stale:", file=sys.stderr)
        for line in stale:
            print(f"  {line}", file=sys.stderr)
        print("\nRun `just bump-version <version>`, which regenerates them.", file=sys.stderr)
        return False

    total = len(versions) + len(SCHEMA_RELPATHS) + 1
    print(f"OK: all {total} version-carrying files at v{version}")
    return True


def bump(target: str) -> None:
    """Update every version-carrying file except uv.lock, which uv owns.

    Pre-validates the target version and all files before writing any changes.
    If the version is unsupported or a file is missing its version field, the
    script fails without modifying anything.
    """
    try:
        parse_version(target)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("No files were modified.", file=sys.stderr)
        sys.exit(1)

    current = get_current_version()
    if current == target:
        print(f"Version is already {target} - nothing to do.")
        return

    print(f"Bumping: {current} → {target}\n")

    # Phase 1: Pre-validate all files and prepare new contents
    pending: list[tuple[Path, str]] = []
    errors: list[str] = []

    def stage(path: Path, text: str, new_text: str) -> None:
        if new_text == text:
            errors.append(str(path.relative_to(ROOT)))
        else:
            pending.append((path, new_text))

    for pkg in owned_packages():
        text = pkg.pyproject.read_text()
        stage(pkg.pyproject, text, PYPROJECT_VERSION_RE.sub(rf"\g<1>{target}\2", text, count=1))

    for path in package_json_files():
        text = path.read_text()
        stage(path, text, PACKAGE_JSON_VERSION_RE.sub(rf"\g<1>{target}\2", text, count=1))

    for path in schema_files():
        text = path.read_text()
        stage(path, text, SCHEMA_ID_RE.sub(rf"\g<1>{target}\2", text))

    if errors:
        print(f"ERROR: No version field found in: {', '.join(errors)}", file=sys.stderr)
        print("No files were modified.", file=sys.stderr)
        sys.exit(1)

    # Phase 2: Write all files (only reached if all pre-checks passed)
    for path, new_text in pending:
        path.write_text(new_text)
        print(f"  ✓ {path.relative_to(ROOT)}")

    print(f"\nDone. Updated {len(pending)} files to v{target}.")
    print("uv.lock is owned by uv and is NOT written here - `just bump-version`")
    print("runs `uv lock` for it. If you called this script directly, run that")
    print("now, or --check will fail.")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--check":
        sys.exit(0 if check_consistency() else 1)
    elif arg == "--current":
        print(get_current_version())
    elif arg == "--check-release":
        release_ref = sys.argv[2] if len(sys.argv) > 2 else "origin/release"
        sys.exit(0 if check_release_bump(release_ref) else 1)
    elif arg.startswith("-"):
        print(f"Unknown flag: {arg}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)
    else:
        # Accept a leading 'v' (e.g. "v0.20.0" → "0.20.0")
        bump(arg.removeprefix("v"))


if __name__ == "__main__":
    main()
