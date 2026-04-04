#!/usr/bin/env python3
"""Bump version across all Syntropic137 packages.

Usage:
    python scripts/bump_version.py 0.20.0          # Update all 12 files
    python scripts/bump_version.py --check          # Validate all files match
    python scripts/bump_version.py --current        # Print current version

This script updates the 12 tracked version files. Submodule versions
(event-sourcing-platform, agentic-primitives, openclaw-plugin) are
intentionally excluded — they have independent versioning.

All files are pre-validated before any writes occur. If any file is
missing a version field, the script fails without modifying anything.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Hardcoded list — matches the 12 files in every "chore: bump version" commit.
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
    ROOT / "apps/syn-pulse-ui/package.json",
]

# Semver-ish: 0.19.0, 0.20.0-beta.1, 1.0.0-rc.2, etc.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")

PYPROJECT_VERSION_RE = re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE)
PACKAGE_JSON_VERSION_RE = re.compile(r'^(\s*"version"\s*:\s*")[^"]*(")', re.MULTILINE)


def read_pyproject_version(path: Path) -> str | None:
    text = path.read_text()
    m = re.search(r'^version\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return m.group(1) if m else None


def read_package_json_version(path: Path) -> str | None:
    data = json.loads(path.read_text())
    return data.get("version")


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


def check_consistency() -> bool:
    """Validate all 13 files have the same version. Returns True if consistent."""
    versions = read_all_versions()
    unique = set(versions.values())

    if None in unique:
        missing = [str(p.relative_to(ROOT)) for p, v in versions.items() if v is None]
        print(f"ERROR: Could not read version from: {', '.join(missing)}", file=sys.stderr)
        return False

    if len(unique) == 1:
        print(f"OK: All 13 files at v{unique.pop()}")
        return True

    print("ERROR: Version mismatch across files:", file=sys.stderr)
    for path, version in sorted(versions.items(), key=lambda x: str(x[0])):
        rel = path.relative_to(ROOT)
        print(f"  {rel}: {version}", file=sys.stderr)
    return False


def bump(target: str) -> None:
    """Update all 13 files to the target version.

    Pre-validates all files before writing any changes. If any file
    is missing a version field, fails without modifying anything.
    """
    if not VERSION_RE.match(target):
        print(
            f"ERROR: Invalid version '{target}'. Expected semver (e.g., 0.20.0 or 0.20.0-beta.1)",
            file=sys.stderr,
        )
        sys.exit(1)

    current = get_current_version()
    if current == target:
        print(f"Version is already {target} — nothing to do.")
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

    if errors:
        print(f"ERROR: No version field found in: {', '.join(errors)}", file=sys.stderr)
        print("No files were modified.", file=sys.stderr)
        sys.exit(1)

    # Phase 2: Write all files (only reached if all pre-checks passed)
    for path, new_text in pending:
        path.write_text(new_text)
        print(f"  ✓ {path.relative_to(ROOT)}")

    print(f"\nDone. Updated {len(pending)} files to v{target}.")
    print(f"Next: git add -A && git commit -m 'chore: bump version to v{target}'")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--check":
        sys.exit(0 if check_consistency() else 1)
    elif arg == "--current":
        print(get_current_version())
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
