"""Fitness function: no release number is written into Python source (#1389).

A version with two homes drifts the first time a bump misses one, and then a
reported version is not evidence of what is running (#1380). syn-api and
syn-collector were fixed in #1382 by reading installed metadata; this check
stops the defect coming back anywhere, in two shapes:

* a module-level ``__version__`` bound to a string literal;
* a ``FastAPI(...)`` call (or a subclass whose name ends in ``FastAPI``) given
  a string literal ``version=``.

Derive the value from ``importlib.metadata`` instead, or drop the dunder when
nothing reads it.

Scope: every tracked ``*.py`` in this repo AND in each checked-out submodule
(``git ls-files --recurse-submodules``), test files excluded. A submodule that
is not checked out is simply not listed. Submodule code cannot be fixed here,
so its known violations are exact-count entries in
``[hardcoded_version_literals]`` of ``fitness_exceptions.toml``, each naming an
issue. Only paths inside a submodule may be listed: this repo's own code gets
no exceptions. A listed file that now has fewer violations fails as stale, so
the table only shrinks.
"""

from __future__ import annotations

import ast
import subprocess
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import load_exceptions, repo_root

if TYPE_CHECKING:
    from pathlib import Path

_SECTION = "hardcoded_version_literals"


def _is_str_literal(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _module_level_statements(body: list[ast.stmt]) -> list[ast.stmt]:
    """Statements that run at import: the module body, through if/try blocks."""
    found: list[ast.stmt] = []
    for stmt in body:
        found.append(stmt)
        if isinstance(stmt, ast.If):
            found.extend(_module_level_statements(stmt.body + stmt.orelse))
        elif isinstance(stmt, ast.Try):
            handlers = [s for h in stmt.handlers for s in h.body]
            found.extend(
                _module_level_statements(stmt.body + handlers + stmt.orelse + stmt.finalbody)
            )
    return found


def _binds_dunder(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Assign):
        names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
        return "__version__" in names and _is_str_literal(stmt.value)
    if isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        return (
            isinstance(target, ast.Name)
            and target.id == "__version__"
            and _is_str_literal(stmt.value)
        )
    return False


def _callee(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def violations(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    """Every hardcoded release number in ``source``, as (line, shape)."""
    tree = ast.parse(source, filename)
    found = [
        (stmt.lineno, "literal __version__")
        for stmt in _module_level_statements(tree.body)
        if _binds_dunder(stmt)
    ]
    found.extend(
        (node.lineno, "literal FastAPI(version=...)")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _callee(node).endswith("FastAPI")
        and any(k.arg == "version" and _is_str_literal(k.value) for k in node.keywords)
    )
    return sorted(found)


def _is_test_file(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return (
        "tests" in parts
        or "test" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _tracked_python(root: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--recurse-submodules", "--", "*.py"],
        check=True,
        capture_output=True,
    ).stdout.decode()
    return sorted(name for name in listed.split("\0") if name and not _is_test_file(name))


def _submodule_paths(root: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line.split("\t", 1)[1] for line in listed.splitlines() if line.startswith("160000 ")]


def _found(root: Path) -> dict[str, list[tuple[int, str]]]:
    result: dict[str, list[tuple[int, str]]] = {}
    for rel in _tracked_python(root):
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


@pytest.mark.architecture
class TestNoHardcodedVersionLiterals:
    def test_no_release_number_is_written_into_source(self) -> None:
        root = repo_root()
        allowed = load_exceptions(root).get(_SECTION, {})
        over = {
            rel: hits
            for rel, hits in _found(root).items()
            if len(hits) > int(allowed.get(rel, {}).get("count", 0))
        }
        assert not over, (
            "Hardcoded release number (#1389). Read it from importlib.metadata "
            "(see syn_collector.collector.version), or delete a __version__ nothing "
            "reads:\n"
            + "\n".join(
                f"  {rel}:{line}: {shape}" for rel, hits in over.items() for line, shape in hits
            )
        )

    def test_exceptions_are_submodule_only_explained_and_not_stale(self) -> None:
        root = repo_root()
        allowed: dict[str, dict[str, str | int]] = load_exceptions(root).get(_SECTION, {})
        submodules = _submodule_paths(root)
        found = _found(root)
        problems: list[str] = []
        for rel, entry in sorted(allowed.items()):
            if not any(rel.startswith(f"{sub}/") for sub in submodules):
                problems.append(f"{rel}: not inside a submodule; fix it here instead")
            if not entry.get("issue"):
                problems.append(f"{rel}: no issue")
            if not (root / rel).is_file():
                continue  # submodule not checked out: nothing to measure
            if len(found.get(rel, [])) < int(str(entry.get("count", 0))):
                problems.append(f"{rel}: fewer violations than listed; lower or delete the entry")
        assert not problems, f"[{_SECTION}] in fitness_exceptions.toml:\n  " + "\n  ".join(problems)


#: Planted sources; each must be caught with no allowlist involved.
PLANTED: dict[str, str] = {
    "plain dunder": '__version__ = "0.1.0"\n',
    "annotated dunder": '__version__: str = "1.2.3"\n',
    "chained dunder": '__version__ = VERSION = "1.2.3"\n',
    "dunder under if": 'import sys\nif sys.version_info >= (3, 12):\n    __version__ = "1"\n',
    "dunder in try": 'try:\n    __version__ = "1"\nexcept Exception:\n    pass\n',
    "FastAPI kwarg": 'from fastapi import FastAPI\napp = FastAPI(version="0.1.0")\n',
    "fastapi.FastAPI": 'import fastapi\napp = fastapi.FastAPI(title="x", version="2")\n',
    "FastAPI subclass": 'app = _TimedFastAPI(version="0.5.1")\n',
}

#: Must NOT be caught: derived values, and literals that are not a release slot.
CLEAN: dict[str, str] = {
    "derived dunder": "from importlib.metadata import version\n__version__ = version('x')\n",
    "derived FastAPI": "app = FastAPI(version=version_string())\n",
    "function-local": 'def f():\n    __version__ = "1"\n    return __version__\n',
    "other kwarg": 'app = FastAPI(title="0.1.0")\n',
    "other callee": 'x = Model(version="1.0.0")\n',
}


@pytest.mark.architecture
@pytest.mark.parametrize("source", PLANTED.values(), ids=PLANTED.keys())
def test_planted_literal_is_caught(source: str) -> None:
    assert violations(source)


@pytest.mark.architecture
@pytest.mark.parametrize("source", CLEAN.values(), ids=CLEAN.keys())
def test_clean_source_is_not_flagged(source: str) -> None:
    assert not violations(source)


@pytest.mark.architecture
def test_ui_feedback_main_as_it_was_is_caught() -> None:
    """The real pre-#1389 shape, not a near miss."""
    before = (
        "from fastapi import FastAPI\n"
        "app = FastAPI(\n"
        '    title="UI Feedback API",\n'
        '    description="REST API for capturing and managing UI feedback",\n'
        '    version="0.1.0",\n'
        "    lifespan=lifespan,\n"
        ")\n"
    )
    assert violations(before) == [(2, "literal FastAPI(version=...)")]
