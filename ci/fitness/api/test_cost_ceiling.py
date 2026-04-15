"""Fitness function: cost ceiling enforcement.

The dispatch chain must enforce a per-hour rate limit on workflow
executions. This prevents unbounded LLM/compute spend from a
misconfigured trigger or replay storm.

Principle: 7. Cost Boundaries (docs/architecture/architectural-fitness.md)
Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import ast
import importlib
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import repo_root

if TYPE_CHECKING:
    from pathlib import Path

# The file that owns the dispatch chain
_DISPATCH_PROJECTION = (
    "packages/syn-domain/src/syn_domain/contexts/github/"
    "slices/dispatch_triggered_workflow/projection.py"
)


def _file_contains_method(path: Path, method_name: str) -> bool:
    """Check if a Python file defines a method with the given name."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
        for node in ast.walk(tree)
    )


def _method_is_called_in(path: Path, caller: str, callee: str) -> bool:
    """Check if `caller` method calls `callee` (as self.<callee>())."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == caller:
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == callee
                ):
                    return True
    return False


@pytest.mark.architecture
class TestCostCeiling:
    """Dispatch chain must enforce cost boundaries."""

    def test_dispatch_rate_limit_method_exists(self) -> None:
        """WorkflowDispatchProjection must define _check_dispatch_rate()."""
        root = repo_root()
        path = root / _DISPATCH_PROJECTION
        assert path.exists(), f"Dispatch projection not found: {_DISPATCH_PROJECTION}"
        assert _file_contains_method(path, "_check_dispatch_rate"), (
            "WorkflowDispatchProjection must define _check_dispatch_rate() "
            "to enforce per-hour dispatch rate limiting."
        )

    def test_budget_check_method_exists(self) -> None:
        """WorkflowDispatchProjection must define _check_budget()."""
        root = repo_root()
        path = root / _DISPATCH_PROJECTION
        assert path.exists(), f"Dispatch projection not found: {_DISPATCH_PROJECTION}"
        assert _file_contains_method(path, "_check_budget"), (
            "WorkflowDispatchProjection must define _check_budget() "
            "to validate spend budget before dispatch."
        )

    def test_process_pending_calls_rate_check(self) -> None:
        """process_pending() must call _check_dispatch_rate() before dispatching."""
        root = repo_root()
        path = root / _DISPATCH_PROJECTION
        assert _method_is_called_in(path, "process_pending", "_check_dispatch_rate"), (
            "process_pending() must call _check_dispatch_rate() to enforce "
            "the per-hour dispatch rate limit before dispatching workflows."
        )

    def test_dispatch_record_calls_budget_check(self) -> None:
        """_dispatch_record() must call _check_budget() before executing."""
        root = repo_root()
        path = root / _DISPATCH_PROJECTION
        assert _method_is_called_in(path, "_dispatch_record", "_check_budget"), (
            "_dispatch_record() must call _check_budget() to validate "
            "spend budget before dispatching each workflow."
        )

    def test_rate_limit_config_has_bounded_default(self) -> None:
        """max_dispatches_per_hour must have a finite positive default."""
        settings_mod = importlib.import_module("syn_shared.settings.polling")
        polling_cls = getattr(settings_mod, "PollingSettings", None)
        assert polling_cls is not None, (
            "PollingSettings class not found in syn_shared.settings.polling"
        )

        # Get the default value from the field
        field_info = polling_cls.model_fields.get("max_dispatches_per_hour")
        assert field_info is not None, "max_dispatches_per_hour field not found in PollingSettings"
        assert field_info.default is not None, "max_dispatches_per_hour must have a default value"
        assert isinstance(field_info.default, int), "max_dispatches_per_hour default must be an int"
        assert field_info.default > 0, (
            f"max_dispatches_per_hour default must be positive, got {field_info.default}. "
            "A default of 0 disables rate limiting entirely."
        )
        assert field_info.default <= 1000, (
            f"max_dispatches_per_hour default is {field_info.default}, which seems too high. "
            "Review whether this is intentional - each dispatch costs real money."
        )
