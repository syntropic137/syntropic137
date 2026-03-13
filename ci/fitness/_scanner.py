"""Cognitive complexity scanner implementing the SonarSource spec.

AST-based analysis that computes cognitive complexity and LOC for Python files.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class FunctionMetrics:
    name: str
    lineno: int
    cog: int
    loc: int


@dataclass
class FileMetrics:
    path: Path
    loc: int  # non-blank, non-comment lines
    total_cog: int  # sum of function COGs
    functions: list[FunctionMetrics]


class _CognitiveComplexityVisitor(ast.NodeVisitor):
    """Compute cognitive complexity for a single function body."""

    def __init__(self, func_name: str) -> None:
        self._func_name = func_name
        self._nesting: int = 0
        self.complexity: int = 0

    def _increment(self, nesting_bonus: bool = True) -> None:
        self.complexity += 1 + (self._nesting if nesting_bonus else 0)

    def _visit_with_nesting(self, node: ast.AST) -> None:
        self._increment(nesting_bonus=True)
        self._nesting += 1
        self.generic_visit(node)
        self._nesting -= 1

    def visit_If(self, node: ast.If) -> None:
        self._increment(nesting_bonus=True)
        # Visit the test expression (catches BoolOp in conditions)
        self.visit(node.test)
        self._nesting += 1
        for child in node.body:
            self.visit(child)
        self._nesting -= 1
        # elif chains: +1 each (no nesting bonus for elif)
        # else: +1 (no nesting bonus)
        for handler in node.orelse:
            if isinstance(handler, ast.If):
                # elif
                self._increment(nesting_bonus=False)
                self.visit(handler.test)
                self._nesting += 1
                for child in handler.body:
                    self.visit(child)
                self._nesting -= 1
                # Continue processing elif's orelse
                for sub in handler.orelse:
                    if isinstance(sub, ast.If):
                        self._process_elif_chain(sub)
                    else:
                        # else after elif
                        self._increment(nesting_bonus=False)
                        self._nesting += 1
                        self.visit(sub)
                        self._nesting -= 1
            else:
                # else
                self._increment(nesting_bonus=False)
                self._nesting += 1
                self.visit(handler)
                self._nesting -= 1

    def _process_elif_chain(self, node: ast.If) -> None:
        """Process remaining elif/else in a chain."""
        self._increment(nesting_bonus=False)
        self.visit(node.test)
        self._nesting += 1
        for child in node.body:
            self.visit(child)
        self._nesting -= 1
        for handler in node.orelse:
            if isinstance(handler, ast.If):
                self._process_elif_chain(handler)
            else:
                self._increment(nesting_bonus=False)
                self._nesting += 1
                self.visit(handler)
                self._nesting -= 1

    def visit_For(self, node: ast.For) -> None:
        self._visit_with_nesting(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_with_nesting(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._visit_with_nesting(node)

    def visit_With(self, node: ast.With) -> None:
        self._visit_with_nesting(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with_nesting(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_with_nesting(node)

    def visit_Match(self, node: ast.Match) -> None:
        # match statement itself gets +1 + nesting
        self._increment(nesting_bonus=True)
        self._nesting += 1
        self.generic_visit(node)
        self._nesting -= 1

    def visit_Assert(self, node: ast.Assert) -> None:
        # BoolOp in assert is handled by visit_BoolOp via generic_visit
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # +1 for each sequence of boolean operators (switching type costs +1)
        # A single `and` or `or` chain = +1
        # Mixed `a and b or c` = +2
        self._increment(nesting_bonus=False)
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        # Ternary: a if cond else b → +1 + nesting
        self._visit_with_nesting(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Recursion: +1 if function calls itself
        if isinstance(node.func, ast.Name) and node.func.id == self._func_name:
            self._increment(nesting_bonus=False)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Nested function: increases nesting for its body
        self._nesting += 1
        self.generic_visit(node)
        self._nesting -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._nesting += 1
        self.generic_visit(node)
        self._nesting -= 1

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._nesting += 1
        self.generic_visit(node)
        self._nesting -= 1


def _count_function_loc(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count lines in a function (end_lineno - lineno + 1)."""
    if node.end_lineno is not None:
        return node.end_lineno - node.lineno + 1
    return 1


def compute_function_complexity(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> FunctionMetrics:
    """Compute cognitive complexity for a single function/method."""
    visitor = _CognitiveComplexityVisitor(node.name)
    for child in ast.iter_child_nodes(node):
        visitor.visit(child)
    return FunctionMetrics(
        name=node.name,
        lineno=node.lineno,
        cog=visitor.complexity,
        loc=_count_function_loc(node),
    )


def _count_loc(source: str) -> int:
    """Count non-blank, non-comment lines. Docstrings count as code."""
    count = 0
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        count += 1
    return count


def _collect_functions(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect all top-level and class-level function definitions."""
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node)
    return functions


def scan_file(path: Path) -> FileMetrics:
    """Scan a Python file and return its metrics."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    loc = _count_loc(source)

    functions = _collect_functions(tree)
    func_metrics = [compute_function_complexity(f) for f in functions]
    total_cog = sum(fm.cog for fm in func_metrics)

    return FileMetrics(
        path=path,
        loc=loc,
        total_cog=total_cog,
        functions=func_metrics,
    )
