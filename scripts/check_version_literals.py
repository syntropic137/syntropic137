"""Find release numbers written into Python source (#1389).

A version with two homes drifts the first time a bump misses one, and then a
reported version is not evidence of what is running (#1380). Two shapes count:

* ``__version__`` bound to a string literal at MODULE SCOPE, which is every
  statement that runs at import: the module body and the bodies of any
  compound statement in it (``if``, ``try``/``try*``, ``with``, ``for``,
  ``while``, ``match``), but never a function or class body;
* a call to ``fastapi.FastAPI``, or to a class derived from it, with a string
  literal ``version=``.

FASTAPI IS RESOLVED, NOT SPELLED. A callee counts when it reaches
``fastapi.FastAPI`` through the module's own bindings: ``from fastapi import
FastAPI as API``, ``import fastapi as f`` then ``f.FastAPI``, a rename by
assignment (``API = FastAPI``, chains included) and a subclass
(``class Timed(FastAPI)``). A name that merely ends in ``FastAPI`` and binds to
nothing of the kind does not count. Matching the spelling instead would let a
one-line rename dodge the gate and flag unrelated callees, the same failure
``check_untyped_dicts.py`` closed in #1188.

The fitness function ``ci/fitness/code_quality/test_no_hardcoded_version_literals.py``
runs this over the repo and its submodules; ``scripts/tests/test_check_version_literals.py``
pins the detector.
"""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

DUNDER = "literal __version__"
FASTAPI = "literal FastAPI(version=...)"

_FASTAPI_MODULE = "fastapi"
_FASTAPI_CLASS = "FastAPI"


@dataclass(frozen=True)
class Finding:
    """One hardcoded release number."""

    line: int
    shape: str


@dataclass(frozen=True)
class ExceptionEntry:
    """A ``[hardcoded_version_literals]`` row: an exact count and its issue."""

    count: int
    issue: str


def _is_str_literal(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def module_scope_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Every statement that runs at import, through any compound statement.

    Generic over the AST rather than a list of compound types, so a statement
    kind added to Python later is traversed without an edit here. Functions
    and classes open a new scope and are not entered.
    """
    for stmt in body:
        yield stmt
        if isinstance(stmt, _SCOPES):
            continue
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.stmt):
                yield from module_scope_statements([child])
            elif isinstance(child, ast.excepthandler | ast.match_case):
                yield from module_scope_statements(child.body)


def _dunder_pairs(target: ast.expr, value: ast.expr) -> Iterator[tuple[str, ast.expr]]:
    if isinstance(target, ast.Name):
        yield target.id, value
    elif (
        isinstance(target, ast.Tuple | ast.List)
        and isinstance(value, ast.Tuple | ast.List)
        and len(target.elts) == len(value.elts)
    ):
        for t, v in zip(target.elts, value.elts, strict=True):
            yield from _dunder_pairs(t, v)


def _binds_literal_dunder(stmt: ast.stmt) -> bool:
    pairs: list[tuple[str, ast.expr]] = []
    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            pairs.extend(_dunder_pairs(target, stmt.value))
    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
        pairs.extend(_dunder_pairs(stmt.target, stmt.value))
    return any(name == "__version__" and _is_str_literal(v) for name, v in pairs)


@dataclass(frozen=True)
class _Bindings:
    """What a module's names resolve to, as far as FastAPI is concerned."""

    modules: frozenset[str]  # local names bound to the fastapi package
    constructors: frozenset[str]  # local names bound to FastAPI or a subclass

    def is_constructor(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.constructors
        return (
            isinstance(node, ast.Attribute)
            and node.attr == _FASTAPI_CLASS
            and isinstance(node.value, ast.Name)
            and node.value.id in self.modules
        )


def _bindings(tree: ast.Module) -> _Bindings:
    """Resolve imports, renames and subclasses to a fixpoint.

    Every binding anywhere in the module counts, as in ``check_untyped_dicts``:
    a rename inside a function constructs just as well, and which binding is in
    scope at a given call cannot be known statically.
    """
    modules: set[str] = set()
    constructors: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _FASTAPI_MODULE or alias.name.startswith("fastapi."):
                    # ``import fastapi.applications`` binds ``fastapi`` itself.
                    modules.add(alias.asname or _FASTAPI_MODULE)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module == _FASTAPI_MODULE or node.module.startswith("fastapi."))
        ):
            for alias in node.names:
                if alias.name == _FASTAPI_CLASS:
                    constructors.add(alias.asname or alias.name)
    changed = True
    while changed:
        changed = False
        resolved = _Bindings(frozenset(modules), frozenset(constructors))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Assign) and resolved.is_constructor(node.value):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif (
                isinstance(node, ast.AnnAssign)
                and node.value is not None
                and isinstance(node.target, ast.Name)
                and resolved.is_constructor(node.value)
            ):
                names = [node.target.id]
            elif isinstance(node, ast.ClassDef) and any(
                resolved.is_constructor(base) for base in node.bases
            ):
                names = [node.name]
            for name in names:
                if name not in constructors:
                    constructors.add(name)
                    changed = True
    return _Bindings(frozenset(modules), frozenset(constructors))


def violations(source: str, filename: str = "<string>") -> list[Finding]:
    """Every hardcoded release number in ``source``."""
    tree = ast.parse(source, filename)
    found = [
        Finding(stmt.lineno, DUNDER)
        for stmt in module_scope_statements(tree.body)
        if _binds_literal_dunder(stmt)
    ]
    bindings = _bindings(tree)
    found.extend(
        Finding(node.lineno, FASTAPI)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and bindings.is_constructor(node.func)
        and any(k.arg == "version" and _is_str_literal(k.value) for k in node.keywords)
    )
    return sorted(found, key=lambda f: (f.line, f.shape))


def is_test_file(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return (
        "tests" in parts
        or "test" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def tracked_python(root: Path) -> list[str]:
    """Tracked non-test ``*.py`` in this repo and every checked-out submodule."""
    listed = _git(root, "ls-files", "-z", "--recurse-submodules", "--", "*.py")
    return sorted(name for name in listed.split("\0") if name and not is_test_file(name))


def submodules(root: Path) -> dict[str, bool]:
    """Every submodule path -> whether it is checked out.

    ``git submodule status`` prefixes an uninitialized one with ``-``. That is
    the one state in which a listed file is legitimately absent.
    """
    states: dict[str, bool] = {}
    for line in _git(root, "submodule", "status").splitlines():
        if not line:
            continue
        path = line[1:].split()[1]
        states[path] = not line.startswith("-")
    return states


def scan(root: Path) -> dict[str, list[Finding]]:
    result: dict[str, list[Finding]] = {}
    for rel in tracked_python(root):
        path = root / rel
        if not path.is_file():
            continue  # deleted but unstaged
        try:
            hits = violations(path.read_text(encoding="utf-8"), rel)
        except (SyntaxError, UnicodeDecodeError):
            continue  # not Python this interpreter parses; not ours to judge
        if hits:
            result[rel] = hits
    return result


def exception_problems(
    entries: Mapping[str, ExceptionEntry],
    found: Mapping[str, int],
    checked_out: Mapping[str, bool],
    file_exists: Callable[[str], bool],
) -> list[str]:
    """What is wrong with the exception table, given what the scan saw.

    An entry must sit inside a submodule (this repo's own code is fixed, not
    excepted) and name an issue. It is stale when its count is above what was
    found, including a file that is gone from a CHECKED-OUT submodule. Only a
    submodule that is not checked out leaves the file unmeasurable.
    """
    problems: list[str] = []
    for rel, entry in sorted(entries.items()):
        owner = next((sub for sub in checked_out if rel.startswith(f"{sub}/")), None)
        if owner is None:
            problems.append(f"{rel}: not inside a submodule; fix it here instead")
            continue
        if not entry.issue:
            problems.append(f"{rel}: no issue")
        if not checked_out[owner]:
            continue  # submodule not checked out: nothing to measure
        if not file_exists(rel):
            problems.append(f"{rel}: file no longer exists in {owner}; delete the entry")
        elif found.get(rel, 0) < entry.count:
            problems.append(f"{rel}: fewer violations than listed; lower or delete the entry")
    return problems
