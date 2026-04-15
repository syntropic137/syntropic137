"""Fitness function: aggregate command handler guards.

Every @command_handler method that mutates aggregate state (calls _apply())
must enforce preconditions before the event is raised. This prevents
invalid state transitions and ensures aggregates are the sole decision-makers.

Principle: 1. Single Ownership (docs/architecture/architectural-fitness.md)

Audit-only handlers that record observations without state transitions
(e.g., record_blocked, record_dispatch_completed) are exempt - they
intentionally accept events in any state.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

import pytest
from ci.fitness.conftest import load_exceptions, repo_root
from ci.fitness.event_sourcing.conftest import aggregate_files

if TYPE_CHECKING:
    from pathlib import Path


_FuncDef = ast.FunctionDef | ast.AsyncFunctionDef


def _find_command_handlers(tree: ast.Module) -> list[tuple[str, _FuncDef]]:
    """Find all @command_handler decorated methods in an AST.

    Returns (handler_name, function_node) pairs.
    """
    handlers: list[tuple[str, _FuncDef]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            # Match @command_handler("...")
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "command_handler"
            ):
                handlers.append((node.name, node))
    return handlers


def _calls_apply(func: _FuncDef) -> bool:
    """Check if the function body calls self._apply() or self._raise_event()."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("_apply", "_raise_event")
        for node in ast.walk(func)
    )


def _has_guard(func: _FuncDef) -> bool:
    """Check if the function has at least one guard (if/raise) before _apply().

    A guard is an ``if`` statement whose body contains a ``raise`` statement.
    We check that at least one such guard appears at the top level of the
    function body before the first _apply()/_raise_event() call.
    """
    for stmt in func.body:
        # Found _apply() call before any guard - no guard exists
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr in ("_apply", "_raise_event")
        ):
            return False

        # Check for if-statement containing a raise
        if isinstance(stmt, ast.If) and _body_contains_raise(stmt.body):
            return True

        # Also check assignment + call patterns (e.g., event = ...; self._apply(event))
        if isinstance(stmt, ast.Assign):
            # Check if the next statement after assignments is _apply
            continue

    # If we got here without finding _apply, the function might use a different
    # pattern. Check if ANY if/raise exists in the function.
    return any(isinstance(stmt, ast.If) and _body_contains_raise(stmt.body) for stmt in func.body)


def _body_contains_raise(stmts: list[ast.stmt]) -> bool:
    """Check if a list of statements contains a Raise node (direct, not nested)."""
    for stmt in stmts:
        if isinstance(stmt, ast.Raise):
            return True
        # Also check: msg = "..."; raise ValueError(msg)
        if isinstance(stmt, ast.Assign):
            continue
        if isinstance(stmt, ast.Expr):
            continue
    return False


def _analyze_file(path: Path, exceptions: dict[str, Any]) -> list[str]:
    """Find @command_handler methods without guards in a file."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    handlers = _find_command_handlers(tree)
    violations: list[str] = []

    # Check file-level exceptions
    rp = str(path.relative_to(repo_root()))
    file_exceptions: dict[str, Any] = exceptions.get(rp, {})
    exempt_methods: list[str] = file_exceptions.get("exempt_methods", [])

    for name, func_node in handlers:
        # Skip explicitly exempted handlers
        if name in exempt_methods:
            continue

        # Only check handlers that call _apply() (state-mutating)
        if not _calls_apply(func_node):
            continue

        if not _has_guard(func_node):
            violations.append(
                f"  {name}() (line {func_node.lineno}): calls _apply() without a "
                f"precondition guard (if/raise)"
            )

    return violations


@pytest.mark.architecture
class TestAggregateGuards:
    """Every state-mutating @command_handler must enforce preconditions."""

    @pytest.mark.parametrize(
        "aggregate_file",
        aggregate_files(),
        ids=lambda p: str(p.relative_to(repo_root())),
    )
    def test_command_handlers_have_guards(self, aggregate_file: Path) -> None:
        """Every @command_handler that calls _apply() must have at least one
        guard (if condition that raises) before the event is applied.

        Audit-only handlers that don't call _apply() are exempt.
        Handlers listed in fitness_exceptions.toml [aggregate_guards]
        exempt_methods are also exempt.
        """
        exceptions = load_exceptions().get("aggregate_guards", {})
        violations = _analyze_file(aggregate_file, exceptions)

        if violations:
            rp = str(aggregate_file.relative_to(repo_root()))
            joined = "\n".join(violations)
            pytest.fail(
                f"Found {len(violations)} unguarded command handler(s) in {rp}:\n"
                f"{joined}\n\n"
                "Every @command_handler that calls _apply() must have a precondition guard:\n"
                "  if <invalid_state>:\n"
                '      msg = "Cannot do X when Y"\n'
                "      raise ValueError(msg)\n\n"
                "If this handler intentionally has no precondition (audit-only event),\n"
                "add it to fitness_exceptions.toml [aggregate_guards] exempt_methods."
            )
