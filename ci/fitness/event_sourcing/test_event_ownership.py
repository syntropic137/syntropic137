"""Fitness function: event ownership invariants.

Enforces core event sourcing rules:
1. DomainEvent subclasses must only be instantiated inside aggregate_*/ directories.
2. _apply() and _raise_event() must only be called from aggregate_*/ files.
3. State mutation (self._field = ...) in aggregates must only occur in
   @event_sourcing_handler or __init__ methods, never in @command_handler methods.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest
from ci.fitness._event_discovery import discover_event_classes
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

if TYPE_CHECKING:
    from pathlib import Path


def _is_in_aggregate_dir(path: Path) -> bool:
    """Check if a file is inside a domain/aggregate_*/ directory."""
    return any(part.startswith("aggregate_") for part in path.parts)


def _is_in_events_dir(path: Path) -> bool:
    """Check if a file is inside a domain/events/ directory."""
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "domain" and i + 1 < len(parts) and parts[i + 1] == "events":
            return True
    return False


# ---------------------------------------------------------------------------
# 3a. Event construction only in aggregates
# ---------------------------------------------------------------------------


def _find_event_constructions_outside_aggregates() -> list[tuple[str, list[int]]]:
    """Find files outside aggregate dirs that construct DomainEvent subclasses."""
    root = repo_root()
    event_classes = discover_event_classes(root)
    event_names = set(event_classes.keys())
    exceptions = load_exceptions(root).get("event_construction_outside_aggregate", {})

    violations: list[tuple[str, list[int]]] = []
    for path in production_files(root):
        if _is_in_aggregate_dir(path) or _is_in_events_dir(path):
            continue

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        construction_lines: list[int] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in event_names
            ):
                construction_lines.append(node.lineno)

        if not construction_lines:
            continue

        rp = rel_path(path, root)
        exc = exceptions.get(rp, {})
        max_constructions = exc.get("max_constructions", 0)
        if len(construction_lines) > max_constructions:
            violations.append((rp, construction_lines))

    return violations


_EVENT_CONSTRUCTION_VIOLATIONS = _find_event_constructions_outside_aggregates()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,construction_lines",
    _EVENT_CONSTRUCTION_VIOLATIONS,
    ids=[v[0].split("/")[-1] for v in _EVENT_CONSTRUCTION_VIOLATIONS]
    if _EVENT_CONSTRUCTION_VIOLATIONS
    else [],
)
def test_event_construction_only_in_aggregates(
    file_path: str, construction_lines: list[int]
) -> None:
    """DomainEvent subclasses must only be instantiated inside aggregate_*/ directories.

    Events are constructed as part of domain logic within aggregates.
    Code outside aggregates should receive events, not create them.
    Deserialization/rehydration is an allowed exception (add to TOML).
    """
    lines_str = ", ".join(str(ln) for ln in construction_lines)
    pytest.fail(
        f"{file_path} constructs DomainEvent subclasses at lines [{lines_str}]. "
        f"Events should only be created inside aggregate_*/ directories. "
        f"If this is legitimate (e.g., deserialization), add to fitness_exceptions.toml "
        f"[event_construction_outside_aggregate] with a GitHub issue link."
    )


# ---------------------------------------------------------------------------
# 3b. _apply() and _raise_event() only in aggregates
# ---------------------------------------------------------------------------


def _find_apply_outside_aggregates() -> list[tuple[str, list[int]]]:
    """Find files outside aggregate dirs that call _apply() or _raise_event()."""
    root = repo_root()
    violations: list[tuple[str, list[int]]] = []

    for path in production_files(root):
        if _is_in_aggregate_dir(path):
            continue

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        call_lines: list[int] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("_apply", "_raise_event")
            ):
                call_lines.append(node.lineno)

        if call_lines:
            rp = rel_path(path, root)
            violations.append((rp, call_lines))

    return violations


_APPLY_VIOLATIONS = _find_apply_outside_aggregates()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,call_lines",
    _APPLY_VIOLATIONS,
    ids=[v[0].split("/")[-1] for v in _APPLY_VIOLATIONS] if _APPLY_VIOLATIONS else [],
)
def test_apply_only_in_aggregates(file_path: str, call_lines: list[int]) -> None:
    """_apply() and _raise_event() must only be called from aggregate_*/ files.

    These are aggregate internals for applying domain events.
    Code outside aggregates must not invoke them.
    """
    lines_str = ", ".join(str(ln) for ln in call_lines)
    pytest.fail(
        f"{file_path} calls _apply()/_raise_event() at lines [{lines_str}]. "
        f"These methods must only be called from aggregate_*/ files."
    )


# ---------------------------------------------------------------------------
# 3c. State mutation only in event handlers (not in command handlers)
# ---------------------------------------------------------------------------


def _has_decorator_named(node: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """Check if a function has a decorator with the given name."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == name:
            return True
        if isinstance(dec, ast.Name) and dec.id == name:
            return True
    return False


def _find_self_assignments(body: list[ast.stmt]) -> list[int]:
    """Find lines with self._field = value assignments in a method body."""
    lines: list[int] = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr.startswith("_")
                ):
                    lines.append(node.lineno)
    return lines


def _find_state_mutation_in_command_handlers() -> list[tuple[str, str, list[int]]]:
    """Find @command_handler methods that mutate self._field directly."""
    from ci.fitness.event_sourcing.conftest import aggregate_files

    root = repo_root()
    violations: list[tuple[str, str, list[int]]] = []

    for path in aggregate_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _has_decorator_named(node, "command_handler"):
                continue

            mutation_lines = _find_self_assignments(node.body)
            if mutation_lines:
                rp = rel_path(path, root)
                violations.append((rp, node.name, mutation_lines))

    return violations


_MUTATION_VIOLATIONS = _find_state_mutation_in_command_handlers()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,method_name,mutation_lines",
    _MUTATION_VIOLATIONS,
    ids=[f"{v[0].split('/')[-1]}::{v[1]}" for v in _MUTATION_VIOLATIONS]
    if _MUTATION_VIOLATIONS
    else [],
)
def test_state_mutation_only_in_event_handlers(
    file_path: str, method_name: str, mutation_lines: list[int]
) -> None:
    """State mutation (self._field = ...) must only occur in @event_sourcing_handler methods.

    @command_handler methods should validate, construct events, and call _apply().
    They must never mutate aggregate state directly — that's the event handler's job.
    """
    lines_str = ", ".join(str(ln) for ln in mutation_lines)
    pytest.fail(
        f"{file_path}::{method_name} mutates state at lines [{lines_str}]. "
        f"@command_handler methods must not assign to self._field. "
        f"Move state changes to @event_sourcing_handler methods."
    )
