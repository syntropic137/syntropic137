"""Fitness function: layer separation.

Ensures domain packages don't import from adapter/API layers at runtime,
and adapter packages don't import from API/CLI layers.
TYPE_CHECKING imports are exempt (they have no runtime effect).

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import pytest
from ci.fitness._imports import runtime_imports
from ci.fitness.conftest import load_exceptions, rel_path, repo_root

# Domain must not import these at runtime
_DOMAIN_FORBIDDEN = {"syn_adapters", "syn_api", "syn_collector"}

# Adapters must not import these at runtime
_ADAPTER_FORBIDDEN = {"syn_api"}


def _check_layer(
    base_dir: str,
    forbidden: set[str],
    exceptions: dict[str, dict[str, object]],
) -> list[tuple[str, int, str]]:
    """Return violations: (rel_path, lineno, imported_module)."""
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
def test_domain_no_runtime_adapter_imports() -> None:
    """Domain layer must not import adapter/API packages at runtime."""
    exceptions = load_exceptions().get("layer_separation", {})
    violations = _check_layer(
        "packages/syn-domain/src",
        _DOMAIN_FORBIDDEN,
        exceptions,
    )
    if violations:
        lines = [f"  {rp}:{line} imports {mod}" for rp, line, mod in violations]
        msg = "Domain layer has forbidden runtime imports:\n" + "\n".join(lines)
        pytest.fail(msg)


@pytest.mark.architecture
def test_adapters_no_api_imports() -> None:
    """Adapter layer must not import API/CLI packages at runtime."""
    exceptions = load_exceptions().get("layer_separation", {})
    violations = _check_layer(
        "packages/syn-adapters/src",
        _ADAPTER_FORBIDDEN,
        exceptions,
    )
    if violations:
        lines = [f"  {rp}:{line} imports {mod}" for rp, line, mod in violations]
        msg = "Adapter layer has forbidden runtime imports:\n" + "\n".join(lines)
        pytest.fail(msg)
