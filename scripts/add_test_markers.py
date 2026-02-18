#!/usr/bin/env python3
"""Auto-add pytest markers to test files based on their dependencies.

This script analyzes test files and adds appropriate markers:
- @pytest.mark.unit: Tests with only mocks, no real I/O
- @pytest.mark.integration: Tests requiring database or external services
- @pytest.mark.e2e: End-to-end tests (usually in scripts/e2e_*)

Usage:
    # Dry run - see what would change
    uv run python scripts/add_test_markers.py --dry-run

    # Apply changes
    uv run python scripts/add_test_markers.py

    # Apply to specific directory
    uv run python scripts/add_test_markers.py packages/syn-domain/tests
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Patterns that indicate integration tests (need real services)
INTEGRATION_PATTERNS = [
    r"postgresql://",
    r"timescale",
    r"asyncpg",
    r"psycopg",
    r"event_store\.connect",
    r"event_store\.pool",
    r"get_event_store\(",
    r"docker",
    r"testcontainers",
    r"container",
    r"/tmp/",
    r"tempfile\.mkdtemp",
]

# Files/paths to skip
SKIP_PATTERNS = [
    r"conftest\.py$",
    r"__init__\.py$",
    r"lib/",
    r"\.venv/",
    r"worktrees/",
]


def should_skip(path: Path) -> bool:
    """Check if file should be skipped."""
    path_str = str(path)
    return any(re.search(pattern, path_str) for pattern in SKIP_PATTERNS)


def has_marker(content: str) -> bool:
    """Check if file already has a test marker."""
    return bool(re.search(r"@pytest\.mark\.(unit|integration|e2e)", content))


def has_pytest_import_at_top(content: str) -> bool:
    """Check if pytest is imported at the top of the file (not inside functions)."""
    lines = content.split("\n")
    in_function = False

    for line in lines[:50]:  # Only check first 50 lines
        stripped = line.strip()

        # Track function/class context by indentation
        if stripped.startswith("def ") or stripped.startswith("async def "):
            in_function = True
        elif stripped.startswith("class "):
            in_function = False

        # Check for pytest import at module level
        if not in_function and stripped == "import pytest":
            return True
        if not in_function and stripped.startswith("from pytest"):
            return True

    return False


def detect_test_type(content: str, filepath: Path) -> str:
    """Detect what type of test this is based on content analysis."""
    if "e2e" in str(filepath).lower():
        return "e2e"

    for pattern in INTEGRATION_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return "integration"

    return "unit"


def add_marker_to_file(filepath: Path, marker: str, dry_run: bool = False) -> bool:
    """Add pytest marker to a test file.

    Strategy:
    1. Find first test class or function
    2. Add marker decorator before it
    3. Add 'import pytest' after __future__ imports if needed
    """
    content = filepath.read_text()

    if has_marker(content):
        return False

    lines = content.split("\n")
    modified = False

    # Step 1: Add pytest import if needed
    if not has_pytest_import_at_top(content):
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip empty lines and docstrings at the start
            if not stripped:
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                # Skip past docstring
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    # Multi-line docstring
                    for j in range(i + 1, len(lines)):
                        if '"""' in lines[j] or "'''" in lines[j]:
                            insert_idx = j + 1
                            break
                else:
                    # Single-line docstring
                    insert_idx = i + 1
                continue

            # After __future__ imports
            if stripped.startswith("from __future__"):
                insert_idx = i + 1
                continue

            # Found first regular import or code
            if stripped.startswith("import ") or stripped.startswith("from "):
                insert_idx = i
                break
            elif stripped and not stripped.startswith("#"):
                # Some other code
                insert_idx = i
                break

        # Insert import pytest
        lines.insert(insert_idx, "import pytest")
        modified = True

    # Step 2: Find first test class or function and add marker
    test_pattern = r"^(class Test\w+|(?:async )?def test_\w+)"

    for i, line in enumerate(lines):
        if re.match(test_pattern, line.strip()):
            # Found first test - add marker before it
            # Check for existing decorators
            insert_idx = i
            while insert_idx > 0 and lines[insert_idx - 1].strip().startswith("@"):
                insert_idx -= 1

            # Add marker with correct indentation
            indent = len(line) - len(line.lstrip())
            marker_line = " " * indent + f"@pytest.mark.{marker}"
            lines.insert(insert_idx, marker_line)
            modified = True
            break

    if not modified:
        return False

    new_content = "\n".join(lines)

    if dry_run:
        print(f"  Would add @pytest.mark.{marker}")
        return True

    filepath.write_text(new_content)
    print(f"  Added @pytest.mark.{marker}")
    return True


def process_directory(
    directory: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    """Process all test files in a directory."""
    stats = {"unit": 0, "integration": 0, "e2e": 0, "skipped": 0, "already_marked": 0}

    test_files = list(directory.rglob("test_*.py")) + list(directory.rglob("*_test.py"))

    for filepath in sorted(test_files):
        if should_skip(filepath):
            if verbose:
                print(f"SKIP: {filepath}")
            stats["skipped"] += 1
            continue

        content = filepath.read_text()

        if has_marker(content):
            if verbose:
                print(f"ALREADY MARKED: {filepath}")
            stats["already_marked"] += 1
            continue

        marker = detect_test_type(content, filepath)
        rel_path = (
            filepath.relative_to(directory) if filepath.is_relative_to(directory) else filepath
        )

        print(f"{marker.upper()}: {rel_path}")

        if add_marker_to_file(filepath, marker, dry_run):
            stats[marker] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Add pytest markers to test files")
    parser.add_argument(
        "directory",
        nargs="?",
        default="packages",
        help="Directory to process (default: packages)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be changed without making changes",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show skipped files",
    )
    parser.add_argument(
        "--apps",
        action="store_true",
        help="Also process apps/ directory",
    )

    args = parser.parse_args()

    directories = [Path(args.directory)]
    if args.apps:
        directories.append(Path("apps"))

    if args.dry_run:
        print("DRY RUN - no files will be modified\n")

    total_stats = {"unit": 0, "integration": 0, "e2e": 0, "skipped": 0, "already_marked": 0}

    for directory in directories:
        if not directory.exists():
            print(f"Directory not found: {directory}")
            continue

        print(f"\n{'=' * 60}")
        print(f"Processing: {directory}")
        print("=" * 60 + "\n")

        stats = process_directory(directory, args.dry_run, args.verbose)

        for key in total_stats:
            total_stats[key] += stats[key]

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Unit tests:        {total_stats['unit']}")
    print(f"  Integration tests: {total_stats['integration']}")
    print(f"  E2E tests:         {total_stats['e2e']}")
    print(f"  Already marked:    {total_stats['already_marked']}")
    print(f"  Skipped:           {total_stats['skipped']}")

    if args.dry_run:
        print("\nRun without --dry-run to apply changes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
