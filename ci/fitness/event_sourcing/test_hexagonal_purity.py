"""Fitness: GitHub bounded context services do not import from adapters.

Catches the failure mode where a developer wires a syn_adapters import
into a domain service file, breaking hexagonal boundaries (ADR-060
Section 10).

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import repo_root

if TYPE_CHECKING:
    from pathlib import Path

_SERVICES_DIR = repo_root() / "packages/syn-domain/src/syn_domain/contexts/github/services"


def _service_files() -> list[Path]:
    if not _SERVICES_DIR.exists():
        return []
    return sorted(p for p in _SERVICES_DIR.glob("*.py") if p.name != "__init__.py")


@pytest.mark.architecture
class TestGitHubBCPurity:
    """github bounded context services must not import syn_adapters."""

    @pytest.mark.parametrize(
        "path",
        _service_files(),
        ids=lambda p: p.name,
    )
    def test_no_adapter_imports(self, path: Path) -> None:
        """No `from syn_adapters` or `import syn_adapters` in service files."""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("syn_adapters"):
                        violations.append(f"{path.name}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and (
                node.module and node.module.startswith("syn_adapters")
            ):
                violations.append(f"{path.name}:{node.lineno} imports from {node.module}")
        assert not violations, (
            "Domain services must not depend on adapters. Use ports under "
            "slices/event_pipeline/ports/ instead.\n  " + "\n  ".join(violations)
        )
