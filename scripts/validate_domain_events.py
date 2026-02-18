#!/usr/bin/env python3
"""Validate that all domain events inherit from DomainEvent with strict settings.

This script scans the syn-domain package for event classes and validates:
1. All events inherit from DomainEvent
2. Events use the @event decorator
3. Events don't override model_config with permissive settings

Run as part of CI to catch events that bypass the type safety layer.

Usage:
    uv run python scripts/validate_domain_events.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Colors for terminal output
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

# Known exceptions - events that use @dataclass (legacy, to be migrated)
# See ADR-032 for migration plan
# All legacy events have been migrated! Keep this for future exceptions if needed.
KNOWN_DATACLASS_EVENTS: set[str] = set()


class EventValidator(ast.NodeVisitor):
    """AST visitor that validates event class definitions."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.events_found: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Check if class is an event and validate it."""
        # Check if class name ends with "Event"
        if not node.name.endswith("Event"):
            self.generic_visit(node)
            return

        self.events_found.append(node.name)

        # Check inheritance
        base_names = [self._get_base_name(base) for base in node.bases]

        if "DomainEvent" not in base_names and "BaseDomainEvent" not in base_names:
            # Check if it inherits from another *Event class (indirect inheritance)
            has_event_base = any(name.endswith("Event") for name in base_names if name)
            if not has_event_base:
                # Check if it's a known exception
                if node.name in KNOWN_DATACLASS_EVENTS:
                    self.warnings.append(
                        f"{self.filepath}:{node.lineno}: {node.name} uses @dataclass "
                        "(legacy, see ADR-032 for migration)"
                    )
                else:
                    self.errors.append(
                        f"{self.filepath}:{node.lineno}: {node.name} does not inherit from DomainEvent"
                    )

        # Check for @event decorator
        has_event_decorator = any(
            self._get_decorator_name(d) == "event" for d in node.decorator_list
        )

        if not has_event_decorator and "DomainEvent" in base_names:
            self.warnings.append(
                f"{self.filepath}:{node.lineno}: {node.name} missing @event decorator"
            )

        # Check for permissive model_config
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "model_config":
                        self._check_model_config(item.value, node.name, node.lineno)

        self.generic_visit(node)

    def _get_base_name(self, base: ast.expr) -> str | None:
        """Extract the name from a base class expression."""
        if isinstance(base, ast.Name):
            return base.id
        if isinstance(base, ast.Attribute):
            return base.attr
        # Handle Generic[T] style
        if isinstance(base, ast.Subscript) and isinstance(base.value, ast.Name):
            return base.value.id
        return None

    def _get_decorator_name(self, decorator: ast.expr) -> str | None:
        """Extract decorator name."""
        if isinstance(decorator, ast.Name):
            return decorator.id
        if isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                return decorator.func.id
            if isinstance(decorator.func, ast.Attribute):
                return decorator.func.attr
        return None

    def _check_model_config(self, value: ast.expr, class_name: str, lineno: int) -> None:
        """Check if model_config has permissive settings."""
        if isinstance(value, ast.Dict):
            for key, val in zip(value.keys, value.values, strict=False):
                # Check for extra='allow' (should be 'forbid')
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "extra"
                    and isinstance(val, ast.Constant)
                    and val.value == "allow"
                ):
                    self.errors.append(
                        f"{self.filepath}:{lineno}: {class_name} has extra='allow' "
                        "(should be 'forbid' for type safety)"
                    )
                # Check for frozen=False (events must be immutable)
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "frozen"
                    and isinstance(val, ast.Constant)
                    and val.value is False
                ):
                    self.errors.append(
                        f"{self.filepath}:{lineno}: {class_name} has frozen=False "
                        "(events must be immutable)"
                    )


def validate_file(filepath: Path) -> tuple[list[str], list[str], list[str]]:
    """Validate a single Python file."""
    try:
        source = filepath.read_text()
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        return [f"{filepath}: Syntax error: {e}"], [], []

    validator = EventValidator(filepath)
    validator.visit(tree)

    return validator.errors, validator.warnings, validator.events_found


def main() -> int:
    """Main entry point."""
    # Find the domain package
    repo_root = Path(__file__).parent.parent
    domain_src = repo_root / "packages" / "syn-domain" / "src"

    if not domain_src.exists():
        print(f"{RED}Error: Domain source not found at {domain_src}{RESET}")
        return 1

    # Find all Python files (excluding test files)
    python_files = [
        f
        for f in domain_src.rglob("*.py")
        if not f.name.startswith("test_") and "conftest" not in f.name
    ]

    all_errors: list[str] = []
    all_warnings: list[str] = []
    all_events: list[str] = []

    for filepath in python_files:
        errors, warnings, events = validate_file(filepath)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        all_events.extend(events)

    # Print results
    print(f"\n{'=' * 60}")
    print("Domain Event Validation Report")
    print(f"{'=' * 60}\n")

    print(f"Found {len(all_events)} event classes in {len(python_files)} files\n")

    if all_warnings:
        print(f"{YELLOW}Warnings ({len(all_warnings)}):{RESET}")
        for warning in all_warnings:
            print(f"  ⚠️  {warning}")
        print()

    if all_errors:
        print(f"{RED}Errors ({len(all_errors)}):{RESET}")
        for error in all_errors:
            print(f"  ❌ {error}")
        print()
        print(f"{RED}Validation FAILED{RESET}")
        return 1

    print(f"{GREEN}✅ All {len(all_events)} events validated successfully!{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
