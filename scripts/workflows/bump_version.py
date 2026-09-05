#!/usr/bin/env python3
"""Bump version across all Syntropic137 packages.

Usage:
    python scripts/workflows/bump_version.py 0.20.0          # Update all 11 files
    python scripts/workflows/bump_version.py --check          # Validate all files match
    python scripts/workflows/bump_version.py --current        # Print current version
    python scripts/workflows/bump_version.py --check-release  # Validate version is bumped vs release branch

This script updates the 11 tracked version files. Submodule versions
(event-sourcing-platform, agentic-primitives, openclaw-plugin) are
intentionally excluded - they have independent versioning.

All files are pre-validated before any writes occur. If any file is
missing a version field, the script fails without modifying anything.

─────────────────────────────────────────────────────────────────────────────
CI DEPENDENCY - this script is called directly by the release gate workflow:
  .github/workflows/_check-version.yml
    → python3 scripts/workflows/bump_version.py --check          (all 11 files match)
    → python3 scripts/workflows/bump_version.py --check-release  (version > release branch)

Also called by the just recipes `check-version` and `bump-version`.
Do not rename flags or change exit codes without updating the workflow.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # scripts/workflows/ -> scripts/ -> repo root

# Hardcoded list - matches the 11 files in every "chore: bump version" commit.
# DO NOT discover dynamically. Submodules must be excluded.
PYPROJECT_FILES = [
    ROOT / "pyproject.toml",
    ROOT / "apps/syn-api/pyproject.toml",
    ROOT / "packages/syn-adapters/pyproject.toml",
    ROOT / "packages/syn-collector/pyproject.toml",
    ROOT / "packages/syn-domain/pyproject.toml",
    ROOT / "packages/syn-perf/pyproject.toml",
    ROOT / "packages/syn-shared/pyproject.toml",
    ROOT / "packages/syn-tokens/pyproject.toml",
]

PACKAGE_JSON_FILES = [
    ROOT / "apps/syn-cli-node/package.json",
    ROOT / "apps/syn-dashboard-ui/package.json",
    ROOT / "apps/syn-docs/package.json",
]

# The four files `bump-version` used to miss. They carry the version too, and
# `--check` reporting "OK: All 11 files" while these were stale is how a build
# shipped schemas advertising the previous version (see the v0.28.0-beta.9 bump).
SCHEMA_FILES = [
    ROOT / "schemas/plugin/workflow.schema.json",
    ROOT / "schemas/plugin/triggers.schema.json",
    ROOT / "schemas/plugin/phase-frontmatter.schema.json",
]

LOCKFILE = ROOT / "uv.lock"

# Only OUR workspace members. `agentic-*` and `event-sourcing-python` are
# submodules with independent versioning and must never be touched here.
LOCKFILE_PACKAGES = (
    "syntropic137",
    "syn-adapters",
    "syn-api",
    "syn-collector",
    "syn-domain",
    "syn-perf",
    "syn-shared",
    "syn-tokens",
)

SCHEMA_ID_RE = re.compile(r"(/schemas/plugin/v)[^/]+(/)")

PYPROJECT_VERSION_RE = re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE)
PACKAGE_JSON_VERSION_RE = re.compile(r'^(\s*"version"\s*:\s*")[^"]*(")', re.MULTILINE)

# Strict semver: 0.19.0, 0.20.0-beta.1, 1.0.0-rc.2, etc.
# Used for both format validation and version comparison.
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def read_pyproject_version(path: Path) -> str | None:
    text = path.read_text()
    m = re.search(r'^version\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return m.group(1) if m else None


def read_package_json_version(path: Path) -> str | None:
    data = json.loads(path.read_text())
    return data.get("version")


def to_pep440(version: str) -> str:
    """semver -> the form uv writes in uv.lock (0.28.0-beta.9 -> 0.28.0b9)."""
    for tag, short in (("-alpha.", "a"), ("-beta.", "b"), ("-rc.", "rc")):
        if tag in version:
            base, num = version.split(tag, 1)
            return f"{base}{short}{num}"
    return version


def read_schema_version(path: Path) -> str | None:
    m = re.search(r"/schemas/plugin/v([^/]+)/", path.read_text())
    return m.group(1) if m else None


def read_lockfile_versions() -> dict[str, str]:
    """Version recorded for each of OUR workspace members in uv.lock."""
    if not LOCKFILE.exists():
        return {}
    found: dict[str, str] = {}
    for block in LOCKFILE.read_text().split("[[package]]"):
        nm = re.search(r'^name = "([^"]+)"', block, re.MULTILINE)
        vm = re.search(r'^version = "([^"]+)"', block, re.MULTILINE)
        if nm and vm and nm.group(1) in LOCKFILE_PACKAGES:
            found[nm.group(1)] = vm.group(1)
    return found


def read_all_versions() -> dict[Path, str | None]:
    versions: dict[Path, str | None] = {}
    for p in PYPROJECT_FILES:
        versions[p] = read_pyproject_version(p)
    for p in PACKAGE_JSON_FILES:
        versions[p] = read_package_json_version(p)
    return versions


def get_current_version() -> str:
    """Read version from root pyproject.toml (source of truth)."""
    v = read_pyproject_version(ROOT / "pyproject.toml")
    if not v:
        print("ERROR: Could not read version from root pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return v


def _parse_semver(v: str) -> tuple[int, int, int, list[str] | None]:
    m = SEMVER_RE.fullmatch(v)
    if not m:
        raise ValueError(f"Invalid semantic version: {v!r}")
    major, minor, patch, prerelease = m.groups()
    pre_parts: list[str] | None = prerelease.split(".") if prerelease else None
    return int(major), int(minor), int(patch), pre_parts


def _compare_prerelease(pr1: list[str] | None, pr2: list[str] | None) -> int:
    if pr1 is None and pr2 is None:
        return 0
    if pr1 is None:
        return 1  # stable > prerelease
    if pr2 is None:
        return -1  # prerelease < stable
    for a, b in zip(pr1, pr2, strict=False):
        a_num, b_num = a.isdigit(), b.isdigit()
        if a_num and b_num:
            if int(a) != int(b):
                return -1 if int(a) < int(b) else 1
        elif a_num != b_num:
            return -1 if a_num else 1
        else:
            if a != b:
                return -1 if a < b else 1
    if len(pr1) == len(pr2):
        return 0
    return -1 if len(pr1) < len(pr2) else 1


def compare_versions(v1: str, v2: str) -> int:
    """Compare two semver strings. Returns -1, 0, or 1."""
    maj1, min1, pat1, pre1 = _parse_semver(v1)
    maj2, min2, pat2, pre2 = _parse_semver(v2)
    core1, core2 = (maj1, min1, pat1), (maj2, min2, pat2)
    if core1 != core2:
        return -1 if core1 < core2 else 1
    return _compare_prerelease(pre1, pre2)


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
    stale: list[str] = []

    # Schema $id values and uv.lock records carry the version too. This check
    # used to stop at the manifests and report OK while these were stale, which
    # is how a build shipped schemas advertising the previous version.
    for path in SCHEMA_FILES:
        got = read_schema_version(path)
        if got != version:
            stale.append(f"{path.relative_to(ROOT)}: {got} (expected {version})")

    expected_lock = to_pep440(version)
    lock_versions = read_lockfile_versions()
    missing = [n for n in LOCKFILE_PACKAGES if n not in lock_versions]
    if missing:
        stale.append(f"uv.lock: no record for {', '.join(sorted(missing))}")
    for name, got in sorted(lock_versions.items()):
        if got != expected_lock:
            stale.append(f"uv.lock [{name}]: {got} (expected {expected_lock})")

    if stale:
        print("ERROR: manifests agree but derived files are stale:", file=sys.stderr)
        for line in stale:
            print(f"  {line}", file=sys.stderr)
        print("\nRun `just bump-version <version>`, which regenerates them.", file=sys.stderr)
        return False

    total = len(versions) + len(SCHEMA_FILES) + 1
    print(f"OK: all {total} version-carrying files at v{version}")
    return True


def bump(target: str) -> None:
    """Update every version-carrying file except uv.lock, which uv owns.

    Pre-validates all files before writing any changes. If any file
    is missing a version field, fails without modifying anything.
    """
    if not SEMVER_RE.fullmatch(target):
        print(
            f"ERROR: Invalid version '{target}'. Expected semver (e.g., 0.20.0 or 0.20.0-beta.1)",
            file=sys.stderr,
        )
        sys.exit(1)

    current = get_current_version()
    if current == target:
        print(f"Version is already {target} - nothing to do.")
        return

    print(f"Bumping: {current} → {target}\n")

    # Phase 1: Pre-validate all files and prepare new contents
    pending: list[tuple[Path, str]] = []
    errors: list[str] = []

    for path in PYPROJECT_FILES:
        text = path.read_text()
        new_text = PYPROJECT_VERSION_RE.sub(rf"\g<1>{target}\2", text, count=1)
        if new_text == text:
            errors.append(str(path.relative_to(ROOT)))
        else:
            pending.append((path, new_text))

    for path in PACKAGE_JSON_FILES:
        text = path.read_text()
        new_text = PACKAGE_JSON_VERSION_RE.sub(rf"\g<1>{target}\2", text, count=1)
        if new_text == text:
            errors.append(str(path.relative_to(ROOT)))
        else:
            pending.append((path, new_text))

    for path in SCHEMA_FILES:
        text = path.read_text()
        new_text = SCHEMA_ID_RE.sub(rf"\g<1>{target}\2", text)
        if new_text == text:
            errors.append(str(path.relative_to(ROOT)))
        else:
            pending.append((path, new_text))

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
        # Strip leading 'v' if provided (e.g., "v0.20.0" → "0.20.0")
        target = arg.lstrip("v")
        bump(target)


if __name__ == "__main__":
    main()
