"""Lint rules enforced as tests — catches patterns ruff cannot.

These tests scan source files for anti-patterns that bypass Python's type
system and have caused production bugs. They run in CI alongside unit tests.

See issue #116: getattr() with string literals hid field-name mismatches
for months because Python type checkers skip dynamic attribute access.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Directories to scan for getattr violations
API_LAYER = Path(__file__).resolve().parents[1] / "src" / "syn_api" / "v1"
DASHBOARD_API = (
    Path(__file__).resolve().parents[3] / "apps" / "syn-dashboard" / "src" / "syn_dashboard" / "api"
)

# Pattern: getattr(anything, "string_literal"   — catches both 2-arg and 3-arg forms
GETATTR_PATTERN = re.compile(r'\bgetattr\(\s*\w+\s*,\s*"[^"]*"')

# Files that are allowed to use getattr (with justification)
ALLOWED_FILES: set[str] = {
    # extract_openapi.py introspects arbitrary module attributes at schema-gen time
    # (not mapping domain→API, so the bug pattern doesn't apply)
}


def _scan_dir(directory: Path) -> list[tuple[str, int, str]]:
    """Scan a directory for getattr violations.

    Returns:
        List of (filepath, line_number, line_text) tuples.
    """
    violations: list[tuple[str, int, str]] = []
    if not directory.exists():
        return violations

    for py_file in sorted(directory.rglob("*.py")):
        if py_file.name in ALLOWED_FILES:
            continue
        for i, line in enumerate(py_file.read_text().splitlines(), 1):
            # Skip comments
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if GETATTR_PATTERN.search(line):
                rel_path = str(py_file.relative_to(directory.parents[2]))
                violations.append((rel_path, i, stripped))
    return violations


@pytest.mark.unit
class TestNoGetattr:
    """Ban getattr(obj, "literal", ...) in the API layer.

    WHY: getattr with string literals bypasses type checking entirely.
    When a domain model field is renamed (e.g. 'name' → 'title'), mypy and
    pyright cannot detect the mismatch because getattr is dynamically resolved.
    This caused two production bugs in issue #116.

    INSTEAD: Use direct attribute access (obj.field) so type checkers catch
    mismatches at lint time. If the attribute may not exist, use:
        obj.field if hasattr(obj, "field") else default
    """

    def test_no_getattr_in_api_v1(self) -> None:
        """No getattr with string literals in packages/syn-api/src/syn_api/v1/."""
        violations = _scan_dir(API_LAYER)
        if violations:
            msg_lines = [
                f"Found {len(violations)} getattr() call(s) with string literals in API layer.",
                "Use direct attribute access instead (see issue #116):",
                "",
            ]
            for path, line, text in violations[:20]:
                msg_lines.append(f"  {path}:{line}: {text}")
            if len(violations) > 20:
                msg_lines.append(f"  ... and {len(violations) - 20} more")
            pytest.fail("\n".join(msg_lines))

    def test_no_getattr_in_dashboard_api(self) -> None:
        """No getattr with string literals in apps/syn-dashboard/src/.../api/."""
        violations = _scan_dir(DASHBOARD_API)
        if violations:
            msg_lines = [
                f"Found {len(violations)} getattr() call(s) with string literals in dashboard API.",
                "Use direct attribute access instead (see issue #116):",
                "",
            ]
            for path, line, text in violations[:20]:
                msg_lines.append(f"  {path}:{line}: {text}")
            pytest.fail("\n".join(msg_lines))
