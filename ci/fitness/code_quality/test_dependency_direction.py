"""Fitness function: package dependency direction.

Enforces that packages respect the dependency hierarchy:
  syn-shared → syn-domain → syn-adapters → syn-api/syn-cli

No package may import from a higher layer at runtime.
TYPE_CHECKING imports are exempt.
"""

from __future__ import annotations

import pytest
from ci.fitness._imports import runtime_imports
from ci.fitness.conftest import load_exceptions, rel_path, repo_root

# Package → set of packages it must NOT import from
_RULES: dict[str, tuple[str, set[str]]] = {
    "syn-domain": (
        "packages/syn-domain/src",
        {"syn_adapters", "syn_api", "syn_cli", "syn_collector"},
    ),
    "syn-shared": (
        "packages/syn-shared/src",
        {"syn_domain", "syn_adapters", "syn_api", "syn_cli"},
    ),
    "syn-adapters": (
        "packages/syn-adapters/src",
        {"syn_api", "syn_cli"},
    ),
}


def _check_package(
    base_dir: str,
    forbidden: set[str],
    exceptions: dict[str, dict[str, object]],
) -> list[tuple[str, int, str]]:
    root = repo_root()
    src_dir = root / base_dir
    if not src_dir.exists():
        return []

    violations = []
    for py_file in sorted(src_dir.rglob("*.py")):
        if py_file.name.startswith("test_") or py_file.name in ("conftest.py", "__init__.py"):
            continue
        rp = rel_path(py_file, root)
        exc_imports = set()
        if rp in exceptions:
            exc_imports = set(exceptions[rp].get("imports", []))  # type: ignore[arg-type]

        try:
            for imp in runtime_imports(py_file):
                for pkg in forbidden:
                    if imp.module.startswith(pkg):
                        if imp.module in exc_imports:
                            continue
                        violations.append((rp, imp.lineno, imp.module))
        except SyntaxError:
            continue

    return violations


@pytest.mark.architecture
@pytest.mark.parametrize("package_name", list(_RULES.keys()))
def test_dependency_direction(package_name: str) -> None:
    """Package must not import from higher-layer packages."""
    base_dir, forbidden = _RULES[package_name]
    exceptions = load_exceptions().get("layer_separation", {})
    violations = _check_package(base_dir, forbidden, exceptions)

    if violations:
        lines = [f"  {rp}:{line} imports {mod}" for rp, line, mod in violations]
        msg = f"{package_name} has forbidden runtime imports:\n" + "\n".join(lines)
        pytest.fail(msg)
