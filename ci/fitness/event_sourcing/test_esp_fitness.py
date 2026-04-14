"""Fitness function: ESP consumer pattern invariants.

Integrates event-sourcing-platform's built-in fitness module into Syn137 CI.
Checks projection purity (whitelist-based import checking) and ProcessManager
structure validation using the ESP-provided fitness checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from ci.fitness.conftest import repo_root
from event_sourcing.fitness import check_projection_purity
from event_sourcing.fitness.process_manager_check import check_process_manager

if TYPE_CHECKING:
    from pathlib import Path

# Project-specific allowed import prefixes (beyond ESP defaults)
_PROJECT_ALLOWED_PREFIXES: frozenset[str] = frozenset(
    {
        "syn_domain.contexts",
        "syn_shared",
        "syn_adapters.projection_stores",
    }
)


def _find_projection_files() -> list[Path]:
    """Find projection .py files that subclass CheckpointedProjection or ProcessManager.

    Only checks files named *projection*.py or *Projection*.py in slices/,
    plus any file that imports from event_sourcing and contains a class
    definition extending CheckpointedProjection or ProcessManager.
    """
    root = repo_root()
    files: list[Path] = []
    for pkg_dir in sorted(root.glob("packages/*/src/**/slices/*")):
        if not pkg_dir.is_dir():
            continue
        for py_file in sorted(pkg_dir.glob("*.py")):
            if py_file.name.startswith("test_") or py_file.name in (
                "conftest.py",
                "__init__.py",
            ):
                continue
            # Only check files that are likely projections
            content = py_file.read_text()
            if "CheckpointedProjection" in content or "ProcessManager" in content:
                files.append(py_file)
    return files


def _find_process_managers() -> list[type]:
    """Find all ProcessManager subclasses registered in the coordinator."""
    from event_sourcing.core.process_manager import ProcessManager

    from syn_domain.contexts.github.slices.dispatch_triggered_workflow import (
        WorkflowDispatchProjection,
    )

    # Collect all known ProcessManager subclasses
    managers: list[type] = []
    if issubclass(WorkflowDispatchProjection, ProcessManager):
        managers.append(WorkflowDispatchProjection)
    return managers


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.architecture
class TestProjectionPurity:
    """Whitelist-based import checking for projection files."""

    @pytest.mark.parametrize(
        "file_path",
        _find_projection_files(),
        ids=lambda p: str(p.relative_to(repo_root())),
    )
    def test_projection_imports_are_allowed(self, file_path: Path) -> None:
        """Every runtime import in a projection must be on the allowed whitelist.

        TYPE_CHECKING imports are always allowed (no runtime effect).
        """
        violations = check_projection_purity(
            file_path,
            allowed_prefixes=_PROJECT_ALLOWED_PREFIXES,
        )
        # Filter to errors only (skip warnings)
        errors = [v for v in violations if v.severity == "error"]
        if errors:
            msg = f"Projection purity violations in {file_path.name}:\n"
            for v in errors:
                msg += f"  line {v.line_number}: {v.message}\n"
            pytest.fail(msg)


@pytest.mark.architecture
class TestProcessManagerStructure:
    """Validate ProcessManager subclasses implement the full interface."""

    @pytest.mark.parametrize(
        "cls",
        _find_process_managers(),
        ids=lambda c: c.__name__,
    )
    def test_process_manager_has_required_methods(self, cls: type) -> None:
        """ProcessManager subclasses must implement process_pending() and get_idempotency_key()."""
        violations = check_process_manager(cast("type", cls))
        if violations:
            msg = f"ProcessManager structure violations in {cls.__name__}:\n"
            for v in violations:
                msg += f"  {v.message}\n"
            pytest.fail(msg)

    def test_workflow_dispatch_is_process_manager(self) -> None:
        """WorkflowDispatchProjection must be a ProcessManager, not a plain projection."""
        from event_sourcing.core.process_manager import ProcessManager

        from syn_domain.contexts.github.slices.dispatch_triggered_workflow import (
            WorkflowDispatchProjection,
        )

        assert issubclass(WorkflowDispatchProjection, ProcessManager), (
            "WorkflowDispatchProjection must extend ProcessManager, not CheckpointedProjection"
        )

    def test_workflow_dispatch_allows_side_effects(self) -> None:
        """WorkflowDispatchProjection.SIDE_EFFECTS_ALLOWED must be True."""
        from syn_domain.contexts.github.slices.dispatch_triggered_workflow import (
            WorkflowDispatchProjection,
        )

        assert WorkflowDispatchProjection.SIDE_EFFECTS_ALLOWED is True, (
            "ProcessManager subclasses must have SIDE_EFFECTS_ALLOWED = True"
        )
