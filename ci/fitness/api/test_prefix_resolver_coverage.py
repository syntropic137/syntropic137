"""Fitness function: prefix resolver coverage for entity show endpoints.

Ensures every API endpoint that accepts an entity ID path parameter uses
``resolve_or_raise()`` from ``syn_api.prefix_resolver`` for partial ID
prefix matching.  Without this, users must type full UUIDs in the CLI
instead of short prefixes like ``syn workflow show b3122``.

See issue #508 for the original prefix resolver implementation.

Required pattern for every GET /{entity_id} endpoint::

    from syn_api.prefix_resolver import resolve_or_raise

    @router.get("/{entity_id}")
    async def get_entity_endpoint(entity_id: str) -> EntityResponse:
        mgr = get_projection_mgr()
        entity_id = await resolve_or_raise(
            mgr.store, "projection_namespace", entity_id, "EntityName"
        )
        ...
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Endpoints exempt from prefix resolution.
# Each entry is (filename_stem, path_param_name).
# Add an entry ONLY for endpoints where the ID is not user-facing
# (e.g. internal IDs, SSE streams, nested paths with pre-resolved parents).
_EXEMPT: set[tuple[str, str]] = {
    # Trigger commands: trigger_id comes from domain events, not user input
    ("commands", "trigger_id"),
    # SSE streams: typically opened via dashboard links with full IDs
    ("sse", "execution_id"),
    # Nested execution path: workflow_id is pre-resolved by the parent route
    ("commands", "execution_id"),
    ("commands", "workflow_id"),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


# Regex: match @router.get(".../{some_id}...") or @router.get(".../{some_id}")
_ROUTE_PATTERN = re.compile(r'@router\.get\(\s*["\']([^"\']*\{(\w+_id)\}[^"\']*)["\']')

_GUIDANCE = (
    "Every GET endpoint with an {entity_id} path parameter must call\n"
    "resolve_or_raise() to support partial ID prefix matching.\n\n"
    "Required pattern:\n"
    "    from syn_api.prefix_resolver import resolve_or_raise\n\n"
    "    entity_id = await resolve_or_raise(\n"
    '        mgr.store, "namespace", entity_id, "EntityName"\n'
    "    )\n\n"
    "See issue #508 and apps/syn-api/src/syn_api/prefix_resolver.py."
)


def _find_show_endpoints_missing_resolver() -> list[str]:
    """Scan API route files for GET-by-ID endpoints missing resolve_or_raise."""
    routes_dir = _repo_root() / "apps" / "syn-api" / "src" / "syn_api" / "routes"
    violations: list[str] = []

    for py_file in sorted(routes_dir.rglob("*.py")):
        if py_file.name.startswith("test_") or py_file.name in (
            "conftest.py",
            "__init__.py",
        ):
            continue

        content = py_file.read_text(encoding="utf-8")
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):
            match = _ROUTE_PATTERN.search(line)
            if not match:
                continue

            route_path = match.group(1)
            param_name = match.group(2)
            file_stem = py_file.stem

            # Check exemptions
            if (file_stem, param_name) in _EXEMPT:
                continue

            # Extract function body: from this decorator to next decorator or EOF
            func_body_lines = []
            for j in range(i, min(i + 60, len(lines))):
                func_body_lines.append(lines[j])
                # Stop at next route decorator (but not the current one)
                if j > i + 1 and re.match(r"\s*@router\.", lines[j]):
                    break

            func_body = "\n".join(func_body_lines)

            if "resolve_or_raise" not in func_body:
                rel = py_file.relative_to(_repo_root())
                violations.append(f"  {rel}:{i}  GET {route_path}  (missing resolve_or_raise)")

    return violations


@pytest.mark.architecture
class TestPrefixResolverCoverage:
    def test_all_show_endpoints_use_prefix_resolver(self) -> None:
        """Every GET /{entity_id} endpoint must call resolve_or_raise().

        Scans all Python files under apps/syn-api/src/syn_api/routes/ for
        @router.get() decorators with {*_id} path parameters.  For each
        match, verifies that the endpoint function body contains a call
        to resolve_or_raise().

        This prevents regressions where new entity endpoints are added
        without partial ID matching, breaking the consistent CLI UX.
        """
        violations = _find_show_endpoints_missing_resolver()

        if violations:
            joined = "\n".join(violations)
            pytest.fail(
                f"Found {len(violations)} GET-by-ID endpoint(s) "
                f"missing resolve_or_raise():\n{joined}\n\n{_GUIDANCE}"
            )
