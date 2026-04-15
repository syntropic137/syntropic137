"""Fitness function: event sourcing pattern compliance.

Enforces that production code follows the command→aggregate→event pattern
rather than imperative coordination via _handle_command().

Rules:
1. Production code must NOT call aggregate._handle_command() directly.
   The correct pattern is to call the aggregate's @command_handler methods
   (e.g., aggregate.start_execution(cmd)) instead of the framework plumbing.
   Test files are exempt (they test the dispatch mechanism).

2. Aggregate files must have matching @command_handler and @event_sourcing_handler
   decorators (every command should produce at least one event).

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root
from ci.fitness.event_sourcing.conftest import aggregate_files

if TYPE_CHECKING:
    from pathlib import Path


def _find_handle_command_calls(path: Path) -> list[int]:
    """Find all lines where _handle_command is called."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_handle_command"
        ):
            lines.append(node.lineno)
    return lines


def _get_violations() -> list[tuple[str, list[int]]]:
    """Find production files that call _handle_command directly."""
    root = repo_root()
    exceptions = load_exceptions(root).get("event_sourcing_handle_command", {})
    violations = []
    for path in production_files(root):
        rp = rel_path(path, root)
        lines = _find_handle_command_calls(path)
        if not lines:
            continue
        exc = exceptions.get(rp, {})
        max_calls = exc.get("max_calls", 0)
        if len(lines) > max_calls:
            violations.append((rp, lines))
    return violations


_VIOLATIONS = _get_violations()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,call_lines",
    _VIOLATIONS,
    ids=[v[0].split("/")[-1] for v in _VIOLATIONS] if _VIOLATIONS else [],
)
def test_no_direct_handle_command(file_path: str, call_lines: list[int]) -> None:
    """Production code must not call aggregate._handle_command() directly.

    Use the aggregate's @command_handler methods instead:
      WRONG:  aggregate._handle_command(StartExecutionCommand(...))
      RIGHT:  aggregate.start_execution(StartExecutionCommand(...))

    _handle_command is framework plumbing, not a domain API.
    """
    lines_str = ", ".join(str(ln) for ln in call_lines)
    pytest.fail(
        f"{file_path} calls _handle_command() directly at lines [{lines_str}]. "
        f"Use the aggregate's @command_handler methods instead. "
        f"If this is a transitional exception, add it to fitness_exceptions.toml "
        f"[event_sourcing_handle_command] with a GitHub issue link."
    )


def _check_aggregate_structure(path: Path) -> list[str]:
    """Check that an aggregate has proper command/event handler structure."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    violations: list[str] = []

    has_aggregate_decorator = False
    command_handlers: list[str] = []
    event_handlers: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Name)
                    and dec.func.id == "aggregate"
                ):
                    has_aggregate_decorator = True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                    if dec.func.id == "command_handler":
                        command_handlers.append(node.name)
                    elif dec.func.id == "event_sourcing_handler":
                        event_handlers.append(node.name)

    if not has_aggregate_decorator:
        return []

    if not command_handlers:
        violations.append("aggregate has no @command_handler methods")
    if not event_handlers:
        violations.append("aggregate has no @event_sourcing_handler methods")
    if command_handlers and not event_handlers:
        violations.append(
            f"aggregate has {len(command_handlers)} command handlers but no event handlers"
        )

    return violations


_AGGREGATE_FILES = aggregate_files()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "agg_file",
    _AGGREGATE_FILES,
    ids=[rel_path(f) for f in _AGGREGATE_FILES],
)
def test_aggregate_has_event_sourcing_structure(agg_file: Path) -> None:
    """Aggregates must have @command_handler and @event_sourcing_handler methods."""
    violations = _check_aggregate_structure(agg_file)
    if violations:
        rp = rel_path(agg_file)
        msg = f"{rp} has event sourcing structural issues:\n" + "\n".join(
            f"  {v}" for v in violations
        )
        pytest.fail(msg)
