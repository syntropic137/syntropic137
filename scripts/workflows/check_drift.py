#!/usr/bin/env python3
"""Check generated artifact drift.

Usage:
    python3 scripts/workflows/check_drift.py <path> [<path> ...]

Exits 0 if all paths are clean (no modified or untracked files).
Exits 1 if any drift is detected, with a summary of what changed.

─────────────────────────────────────────────────────────────────────────────
CI DEPENDENCY - called by the codegen sync check:
  .github/workflows/_check-codegen-sync.yml
    → python3 scripts/workflows/check_drift.py \\
        apps/syn-cli-node/src/generated/ \\
        apps/syn-docs/content/docs/cli/ \\
        apps/syn-docs/content/docs/api/ \\
        apps/syn-docs/openapi.json

To fix a failure locally: just codegen && git add -A && git commit
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def check_drift(paths: list[str]) -> bool:
    """Return True if all paths are clean, False if any drift detected."""
    try:
        changed = _git_diff(paths)
        untracked = _git_untracked(paths)
    except subprocess.CalledProcessError as exc:
        print(f"::error::git command failed: {exc.cmd} (exit {exc.returncode})", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        return False

    if not changed and not untracked:
        print("✓ All generated artifacts are in sync.")
        return True

    print("::error::Generated artifacts are stale. Run 'just codegen' and commit.")
    print()

    if changed:
        _git_diff_stat(paths)

    if untracked:
        print("Untracked files:")
        for f in untracked:
            print(f"  {f}")

    return False


def _git_diff(paths: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", *paths],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _git_untracked(paths: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", *paths],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _git_diff_stat(paths: list[str]) -> None:
    subprocess.run(
        ["git", "diff", "--stat", "--", *paths],
        check=False,
    )


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    paths = sys.argv[1:]

    # Validate paths exist - fail hard so CI catches misconfigured path args
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        for p in missing:
            print(f"::error::Path does not exist: {p}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0 if check_drift(paths) else 1)


if __name__ == "__main__":
    main()
