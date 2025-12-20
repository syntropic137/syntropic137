#!/usr/bin/env python3
"""Check for test debt: xfail, skip, TODO markers that hide broken functionality.

This script should be run in CI to prevent accumulation of test debt.
Exit code 1 if any issues found (unless --warn-only is passed).

Usage:
    python scripts/check_test_debt.py
    python scripts/check_test_debt.py --warn-only  # Don't fail, just warn
    python scripts/check_test_debt.py --strict     # Fail on any debt (default)
"""

import argparse
import re
import sys
from pathlib import Path

# Patterns to search for
# POKA-YOKE: xfail/skip MUST include an issue link (e.g., "#123" or "github.com/...")
PATTERNS = {
    "xfail_no_reason": {
        "regex": r"@pytest\.mark\.xfail\s*\n|@pytest\.mark\.xfail\(\s*\)",
        "severity": "error",
        "message": "xfail without reason - add reason='...' with issue link",
    },
    "skip_no_reason": {
        "regex": r"@pytest\.mark\.skip\s*\n|@pytest\.mark\.skip\(\s*\)",
        "severity": "error",
        "message": "skip without reason - add reason='...' with issue link",
    },
    "todo_in_test": {
        "regex": r"#\s*(TODO|FIXME|XXX|HACK):",
        "severity": "warning",
        "message": "TODO/FIXME in test file",
    },
    "commented_test": {
        "regex": r"^\s*#\s*def test_|^\s*#\s*async def test_",
        "severity": "error",
        "message": "Commented out test - delete or implement",
    },
    "empty_test": {
        "regex": r"def test_\w+\([^)]*\):\s*\n\s*(pass|\.\.\.)\s*\n",
        "severity": "error",
        "message": "Empty test body - implement or remove",
    },
}

# Issue link patterns that are acceptable
ISSUE_LINK_PATTERN = re.compile(r"#\d+|github\.com/[^/]+/[^/]+/issues/\d+")

# Directories to search
SEARCH_DIRS = ["packages", "apps"]

# File patterns
TEST_FILE_PATTERNS = ["test_*.py", "*_test.py"]


def find_test_files(root: Path) -> list[Path]:
    """Find all test files in the project."""
    files = []
    for search_dir in SEARCH_DIRS:
        dir_path = root / search_dir
        if dir_path.exists():
            for pattern in TEST_FILE_PATTERNS:
                files.extend(dir_path.rglob(pattern))
    return sorted(files)


def check_file(filepath: Path) -> list[dict]:
    """Check a single file for test debt patterns."""
    issues = []
    try:
        content = filepath.read_text()
        lines = content.split("\n")
    except Exception as e:
        return [{"file": str(filepath), "line": 0, "pattern": "read_error", "message": str(e)}]

    # Check standard patterns
    for pattern_name, pattern_info in PATTERNS.items():
        regex = re.compile(pattern_info["regex"], re.MULTILINE)

        for i, line in enumerate(lines, 1):
            if regex.search(line):
                issues.append(
                    {
                        "file": str(filepath),
                        "line": i,
                        "pattern": pattern_name,
                        "severity": pattern_info["severity"],
                        "message": pattern_info["message"],
                        "content": line.strip()[:80],
                    }
                )

    # POKA-YOKE: Check xfail/skip have issue links
    xfail_skip_pattern = re.compile(r"@pytest\.mark\.(xfail|skip)\(")
    for i, line in enumerate(lines, 1):
        match = xfail_skip_pattern.search(line)
        if match:
            marker_type = match.group(1)
            # Check if line has an issue link
            if not ISSUE_LINK_PATTERN.search(line):
                issues.append(
                    {
                        "file": str(filepath),
                        "line": i,
                        "pattern": f"{marker_type}_no_issue",
                        "severity": "error",
                        "message": f"{marker_type} without issue link - add '#123' to reason",
                        "content": line.strip()[:80],
                    }
                )

    return issues


def main():
    parser = argparse.ArgumentParser(description="Check for test debt")
    parser.add_argument("--warn-only", action="store_true", help="Don't fail, just warn")
    parser.add_argument("--strict", action="store_true", help="Fail on any debt (default)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    test_files = find_test_files(root)

    all_issues = []
    for filepath in test_files:
        issues = check_file(filepath)
        all_issues.extend(issues)

    # Separate by severity
    errors = [i for i in all_issues if i["severity"] == "error"]
    warnings = [i for i in all_issues if i["severity"] == "warning"]

    if args.json:
        import json

        print(json.dumps({"errors": errors, "warnings": warnings}, indent=2))
    else:
        print("=" * 70)
        print("🔍 TEST DEBT CHECK")
        print("=" * 70)

        if errors:
            print(f"\n❌ ERRORS ({len(errors)}):\n")
            for issue in errors:
                print(f"  {issue['file']}:{issue['line']}")
                print(f"    [{issue['pattern']}] {issue['message']}")
                print(f"    > {issue['content']}")
                print()

        if warnings:
            print(f"\n⚠️  WARNINGS ({len(warnings)}):\n")
            for issue in warnings:
                print(f"  {issue['file']}:{issue['line']}")
                print(f"    [{issue['pattern']}] {issue['message']}")
                print(f"    > {issue['content']}")
                print()

        print("=" * 70)
        print(f"📊 SUMMARY: {len(errors)} errors, {len(warnings)} warnings")
        print("=" * 70)

        if errors:
            print("\n💡 To fix xfail tests:")
            print("   1. Implement the missing functionality")
            print("   2. Remove the @pytest.mark.xfail decorator")
            print("   3. Run the test to verify it passes")
            print()

    # Exit code
    if args.warn_only:
        sys.exit(0)
    elif errors:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
