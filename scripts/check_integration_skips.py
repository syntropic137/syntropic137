"""Find integration tests that can skip without saying so (PC-192/PC-193).

An integration test that skips passes. On a clean runner where an image
defaulted to ``:latest``, a store was not provisioned or an env var was unset,
"passes" means nothing ran, and CI stays green. The fix is not to forbid skips
but to make each one a declared decision with an owner:

    @pytest.mark.integration
    @pytest.mark.may_skip(reason="needs the Docker daemon", issue="#1234")
    def test_reaps_dead_host(...): ...

**Which tests.** A function named ``test_*`` at module level, or in a class
named ``Test*``, in a test module (``test_*.py``/``*_test.py``), that carries
``pytest.mark.integration`` on itself, its class (decorator or ``pytestmark``)
or its module (``pytestmark``).

**What can skip.** Any of these, reached from the test:

- a ``skip``/``skipif`` mark on the test, its class or its module, including
  one carried by ``pytest.param(..., marks=...)`` in a parametrize or in a
  fixture's ``params``;
- a call to ``skip`` or ``importorskip`` on ``pytest`` (or any ``import pytest
  as`` alias of it), in the test, in its module's top level, or in any function
  it calls that resolves to a module-level function here or imported by name
  from a repo module, through any chain of re-exports;
- a fixture that does any of the above: requested as a parameter, through
  ``usefixtures``, or autouse in the test's class, its module or a
  ``conftest.py`` above it. Fixture names resolve as pytest registers them
  (``name=`` first, else the attribute name; class first, then module, then
  conftests), and fixture parameters are followed the same way;
- an xunit setup hook pytest runs before the test: ``setup_module``/
  ``setUpModule``, ``setup_function``, and in its class ``setup_class``/
  ``setup_method``/``setUpClass``/``setUp``.

Calls are followed by name only. A skip behind a method call, a ``getattr`` or
``request.getfixturevalue`` is not seen; that is a false pass, and the reason
the declaration lives on the test rather than being inferred from it.

**What declares it.** ``pytest.mark.may_skip`` on the test, its class or its
module, with ``reason`` a non-empty string literal and ``issue`` a literal
``#N`` or ``owner/repo#N``. A marker missing either is reported on its own,
whether or not the test can skip, so a half-written declaration never counts.

The whole-codebase count of undeclared skips is ratcheted by
``ci/fitness/code_quality/test_integration_skips_are_declared.py``.
"""

from __future__ import annotations

import ast
import enum
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

MARKER = "may_skip"
#: Not in pyproject's ``testpaths`` but run by the integration job all the same.
_EXTRA_TEST_DIRS = ("syn_tests",)
_ISSUE = re.compile(r"^([\w.-]+/[\w.-]+)?#\d+$")
_SKIP_CALLS = frozenset({"skip", "importorskip"})
_SKIP_MARKS = frozenset({"skip", "skipif"})
_FIXTURE_DECORATORS = frozenset({"fixture"})
#: xunit-style setup hooks; pytest registers each as an autouse fixture.
_MODULE_SETUP = frozenset({"setup_module", "setUpModule"})
_FUNCTION_SETUP = frozenset({"setup_function"})
_CLASS_SETUP = frozenset({"setup_class", "setup_method", "setUpClass", "setUp"})

_Fn = ast.FunctionDef | ast.AsyncFunctionDef


class Problem(enum.Enum):
    UNDECLARED = "can skip but declares no may_skip marker"
    NO_REASON = "may_skip marker has no non-empty literal reason"
    NO_ISSUE = "may_skip marker has no literal issue (#N or owner/repo#N)"


@dataclass(frozen=True, order=True)
class Finding:
    path: str  # repo-relative, posix
    line: int
    test: str  # "Class::test" or "test"
    problem: Problem = field(compare=False)

    def __str__(self) -> str:
        return f"{self.path}:{self.line} {self.test}: {self.problem.value}"


def _dotted(expr: ast.expr) -> str:
    if isinstance(expr, ast.Call):
        return _dotted(expr.func)
    if isinstance(expr, ast.Attribute):
        head = _dotted(expr.value)
        return f"{head}.{expr.attr}" if head else ""
    return expr.id if isinstance(expr, ast.Name) else ""


def _mark_name(expr: ast.expr) -> str:
    """``pytest.mark.skipif(...)`` -> ``skipif``; anything else -> ``""``."""
    parts = _dotted(expr).split(".")
    return parts[-1] if len(parts) >= 2 and parts[-2] == "mark" else ""


def _pytestmark(body: Sequence[ast.stmt]) -> list[ast.expr]:
    marks: list[ast.expr] = []
    for stmt in body:
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            marks.extend(value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value])
    return marks


def _fixture_decl(fn: _Fn) -> tuple[str | None, bool] | None:
    """(``name=`` it registers under, if any; is autouse), or None if not a fixture."""
    for dec in fn.decorator_list:
        if _dotted(dec).split(".")[-1] not in _FIXTURE_DECORATORS:
            continue
        keywords = {kw.arg: kw.value for kw in dec.keywords} if isinstance(dec, ast.Call) else {}
        name, autouse = keywords.get("name"), keywords.get("autouse")
        return (
            name.value if isinstance(name, ast.Constant) and isinstance(name.value, str) else None,
            isinstance(autouse, ast.Constant) and autouse.value is True,
        )
    return None


def _fixtures(body: Sequence[ast.stmt]) -> tuple[dict[str, _Fn], list[_Fn]]:
    """Fixtures defined in a module or class body, keyed as pytest registers them:
    by ``name=`` when given, else by the attribute name; and the autouse ones."""
    fixtures: dict[str, _Fn] = {}
    autouse: list[_Fn] = []
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decl = _fixture_decl(stmt)
            if decl is not None:
                fixtures[decl[0] or stmt.name] = stmt
                if decl[1]:
                    autouse.append(stmt)
    return fixtures, autouse


def _params(fn: _Fn) -> list[str]:
    args = fn.args
    return [
        a.arg
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        if a.arg not in {"self", "cls"}
    ]


def _usefixtures(marks: Iterable[ast.expr]) -> list[str]:
    return [
        arg.value
        for mark in marks
        if _mark_name(mark) == "usefixtures" and isinstance(mark, ast.Call)
        for arg in mark.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]


def _own_nodes(fn: _Fn) -> Iterator[ast.AST]:
    """Nodes that run when ``fn`` runs: its body, nested defs included (they are
    usually called from it), decorators and defaults excluded."""
    for stmt in fn.body:
        yield from ast.walk(stmt)


def _module_level_nodes(body: Sequence[ast.stmt]) -> Iterator[ast.AST]:
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def _hooks(body: Sequence[ast.stmt], names: frozenset[str]) -> list[_Fn]:
    return [
        stmt
        for stmt in body
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name in names
    ]


@dataclass
class _Module:
    path: Path
    tree: ast.Module
    functions: dict[str, _Fn]
    fixtures: dict[str, _Fn]
    autouse: list[_Fn]
    imports: dict[str, tuple[str, str]]  # local name -> (module, name)
    pytest_names: frozenset[str]  # names bound to the pytest module itself
    pytest_skip_names: frozenset[str]  # bare names bound to pytest.skip/importorskip

    @property
    def marks(self) -> list[ast.expr]:
        return _pytestmark(self.tree.body)


class Scanner:
    """Parses modules once and answers "can this function skip?" across them.

    ``cls`` threads through fixture lookup because pytest resolves a fixture
    name in the requesting test's class first, then its module, then the
    conftests above it.
    """

    def __init__(self, root: Path, import_roots: Sequence[Path]) -> None:
        self.root = root
        self._import_roots = [root, *import_roots]
        self._modules: dict[Path, _Module | None] = {}
        self._targets: dict[str, Path | None] = {}
        self._skips: dict[tuple[Path, str], bool] = {}

    # -- parsing ------------------------------------------------------------

    def module(self, path: Path) -> _Module | None:
        path = path.resolve()
        if path not in self._modules:
            self._modules[path] = self._parse(path)
        return self._modules[path]

    def _parse(self, path: Path) -> _Module | None:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            return None
        functions: dict[str, _Fn] = {}
        imports: dict[str, tuple[str, str]] = {}
        pytest_names: set[str] = {"pytest"}
        skip_names: set[str] = set()
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[stmt.name] = stmt
            elif isinstance(stmt, ast.Import):
                pytest_names.update(
                    alias.asname for alias in stmt.names if alias.name == "pytest" and alias.asname
                )
            elif isinstance(stmt, ast.ImportFrom):
                base = self._resolve_relative(path, stmt)
                for alias in stmt.names:
                    local = alias.asname or alias.name
                    if stmt.module == "pytest" and alias.name in _SKIP_CALLS:
                        skip_names.add(local)
                    elif base:
                        imports[local] = (base, alias.name)
        fixtures, autouse = _fixtures(tree.body)
        return _Module(
            path,
            tree,
            functions,
            fixtures,
            autouse,
            imports,
            frozenset(pytest_names),
            frozenset(skip_names),
        )

    @staticmethod
    def _resolve_relative(path: Path, stmt: ast.ImportFrom) -> str:
        if not stmt.level:
            return stmt.module or ""
        # Relative: express as a path relative to the importing package, marked
        # with a leading "/" so _import_target knows not to search the roots.
        package = path.parent
        for _ in range(stmt.level - 1):
            package = package.parent
        tail = (stmt.module or "").replace(".", "/")
        return "/" + str(package / tail)

    def _import_target(self, module: str) -> Path | None:
        if module in self._targets:
            return self._targets[module]
        if module.startswith("/"):
            candidates = [Path(module[1:])]
        else:
            rel = module.replace(".", "/")
            candidates = [r / rel for r in self._import_roots]
        self._targets[module] = next(
            (
                path
                for base in candidates
                for path in (base.with_suffix(".py"), base / "__init__.py")
                if path.is_file()
            ),
            None,
        )
        return self._targets[module]

    def _resolve(
        self, mod: _Module, name: str, seen: frozenset[tuple[Path, str]] = frozenset()
    ) -> tuple[_Module, _Fn] | None:
        """The function bound to ``name`` in ``mod``, through any chain of
        ``from x import name`` re-exports (a package ``__init__`` re-exporting
        from a submodule, say)."""
        found = mod.functions.get(name)
        if found is not None:
            return mod, found
        if name not in mod.imports or (mod.path, name) in seen:
            return None
        target_module, target_name = mod.imports[name]
        target_path = self._import_target(target_module)
        target = self.module(target_path) if target_path else None
        if target is None:
            return None
        return self._resolve(target, target_name, seen | {(mod.path, name)})

    def _conftests(self, path: Path) -> Iterator[_Module]:
        """conftest.py modules that apply to ``path``, nearest first."""
        directory = path.parent
        while True:
            conftest = directory / "conftest.py"
            if conftest != path and conftest.is_file():
                mod = self.module(conftest)
                if mod is not None:
                    yield mod
            if directory == self.root or directory.parent == directory:
                return
            directory = directory.parent

    def _fixture_in(self, mod: _Module, name: str) -> tuple[_Module, _Fn] | None:
        """A fixture ``mod`` registers as ``name``: defined there, or imported
        and bound to an attribute pytest registers under ``name``."""
        if name in mod.fixtures:
            return mod, mod.fixtures[name]
        for local in mod.imports:
            found = self._resolve(mod, local)
            decl = _fixture_decl(found[1]) if found is not None else None
            if decl is not None and (decl[0] or local) == name:
                return found
        return None

    def _fixture(
        self, mod: _Module, name: str, cls: ast.ClassDef | None
    ) -> tuple[_Module, _Fn] | None:
        if cls is not None and name in (class_fixtures := _fixtures(cls.body)[0]):
            return mod, class_fixtures[name]
        found = self._fixture_in(mod, name)
        if found is not None:
            return found
        for conftest in self._conftests(mod.path):
            found = self._fixture_in(conftest, name)
            if found is not None:
                return found
        return None

    # -- the question -------------------------------------------------------

    def marks_skip(self, marks: Iterable[ast.expr]) -> bool:
        """A skip/skipif mark anywhere in ``marks``, including one carried by a
        ``pytest.param(..., marks=...)`` inside a parametrize or fixture params."""
        return any(
            isinstance(node, ast.expr) and _mark_name(node) in _SKIP_MARKS
            for mark in marks
            for node in ast.walk(mark)
        )

    def _calls_skip(self, mod: _Module, nodes: Iterable[ast.AST]) -> list[str]:
        """Whether ``nodes`` call a skip directly; else the bare names they call."""
        called: list[str] = []
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            head, _, attr = _dotted(node.func).rpartition(".")
            if head in mod.pytest_names and attr in _SKIP_CALLS:
                return ["<skip>"]
            if not head and attr in mod.pytest_skip_names:
                return ["<skip>"]
            if isinstance(node.func, ast.Name):
                called.append(node.func.id)
        return called

    def module_skips(self, mod: _Module) -> bool:
        """Importing the module can skip it, every test in it is skip-marked, or
        its xunit module setup can skip."""
        if self.marks_skip(mod.marks):
            return True
        if self._calls_skip(mod, _module_level_nodes(mod.tree.body)) == ["<skip>"]:
            return True
        return any(
            self.can_skip(mod, hook, as_fixture=False)
            for hook in _hooks(mod.tree.body, _MODULE_SETUP)
        )

    def can_skip(
        self, mod: _Module, fn: _Fn, *, as_fixture: bool, cls: ast.ClassDef | None = None
    ) -> bool:
        scope = cls.lineno if cls is not None else 0
        key = (mod.path, f"{'fixture' if as_fixture else 'fn'}:{fn.name}:{fn.lineno}:{scope}")
        if key in self._skips:
            return self._skips[key]
        self._skips[key] = False  # cycle guard: a recursion is not a skip
        result = self._can_skip(mod, fn, as_fixture=as_fixture, cls=cls)
        self._skips[key] = result
        return result

    def _can_skip(
        self, mod: _Module, fn: _Fn, *, as_fixture: bool, cls: ast.ClassDef | None
    ) -> bool:
        if self.marks_skip(fn.decorator_list):
            return True
        called = self._calls_skip(mod, _own_nodes(fn))
        if called == ["<skip>"]:
            return True
        for name in called:
            found = self._resolve(mod, name)
            if found is not None and self.can_skip(*found, as_fixture=False):
                return True
        if as_fixture:
            return self.requests_skipping_fixture(mod, _params(fn), cls)
        return False

    def requests_skipping_fixture(
        self, mod: _Module, names: Iterable[str], cls: ast.ClassDef | None = None
    ) -> bool:
        for name in names:
            found = self._fixture(mod, name, cls)
            if found is None:
                continue
            owner, fixture = found
            # A class-local fixture resolves its own requests in that class.
            in_class = cls is not None and any(item is fixture for item in cls.body)
            if self.can_skip(owner, fixture, as_fixture=True, cls=cls if in_class else None):
                return True
        return False

    def parametrized_integration(
        self, mod: _Module, fn: _Fn, cls: ast.ClassDef | None = None, seen: set[int] | None = None
    ) -> bool:
        """Some parametrization of ``fn`` is integration: ``pytest.param(...,
        marks=pytest.mark.integration)`` in its decorators or in the ``params``
        of a fixture it requests, however deep."""
        seen = set() if seen is None else seen
        if id(fn) in seen:
            return False
        seen.add(id(fn))
        if any(
            isinstance(node, ast.expr) and _mark_name(node) == "integration"
            for dec in fn.decorator_list
            for node in ast.walk(dec)
        ):
            return True
        for name in _params(fn):
            found = self._fixture(mod, name, cls)
            if found is not None and self.parametrized_integration(*found, cls, seen):
                return True
        return False

    def autouse_skips(self, mod: _Module) -> bool:
        for owner in (mod, *self._conftests(mod.path)):
            if any(self.can_skip(owner, fn, as_fixture=True) for fn in owner.autouse):
                return True
        return False

    def class_skips(self, mod: _Module, cls: ast.ClassDef, class_marks: list[ast.expr]) -> bool:
        """Every test in ``cls`` can skip: a skip mark on it, an autouse fixture
        it defines, or an xunit class/method setup hook (pytest turns those into
        autouse fixtures, so they run before every test)."""
        if self.marks_skip(class_marks):
            return True
        if any(self.can_skip(mod, fn, as_fixture=True, cls=cls) for fn in _fixtures(cls.body)[1]):
            return True
        return any(
            self.can_skip(mod, hook, as_fixture=False) for hook in _hooks(cls.body, _CLASS_SETUP)
        )

    def function_setup_skips(self, mod: _Module) -> bool:
        """``setup_function`` runs before every module-level test function."""
        return any(
            self.can_skip(mod, hook, as_fixture=False)
            for hook in _hooks(mod.tree.body, _FUNCTION_SETUP)
        )


def _marker_problems(marks: Iterable[ast.expr]) -> tuple[bool, list[Problem]]:
    """(declared, problems) for every may_skip marker in ``marks``."""
    declared = False
    problems: list[Problem] = []
    for mark in marks:
        if _mark_name(mark) != MARKER:
            continue
        declared = True
        keywords = {kw.arg: kw.value for kw in mark.keywords} if isinstance(mark, ast.Call) else {}
        reason, issue = keywords.get("reason"), keywords.get("issue")
        if not (
            isinstance(reason, ast.Constant)
            and isinstance(reason.value, str)
            and reason.value.strip()
        ):
            problems.append(Problem.NO_REASON)
        if not (
            isinstance(issue, ast.Constant)
            and isinstance(issue.value, str)
            and _ISSUE.match(issue.value)
        ):
            problems.append(Problem.NO_ISSUE)
    return declared, problems


def _tests(tree: ast.Module) -> Iterator[tuple[str, _Fn, ast.ClassDef | None]]:
    """(qualified name, function, enclosing ``Test*`` class) for each collected test."""
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith(
            "test"
        ):
            yield stmt.name, stmt, None
        elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
            for item in stmt.body:
                if isinstance(
                    item, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and item.name.startswith("test"):
                    yield f"{stmt.name}::{item.name}", item, stmt


def scan(root: Path, files: Iterable[Path], import_roots: Sequence[Path] = ()) -> list[Finding]:
    """Every integration test in ``files`` that skips undeclared, or declares badly."""
    scanner = Scanner(root.resolve(), [r.resolve() for r in import_roots])
    findings: list[Finding] = []
    for path in files:
        mod = scanner.module(path)
        if mod is None:
            continue
        rel = mod.path.relative_to(scanner.root).as_posix()
        module_marks = mod.marks
        module_wide: bool | None = None  # computed once, only if needed
        for name, fn, cls in _tests(mod.tree):
            class_marks = [*cls.decorator_list, *_pytestmark(cls.body)] if cls else []
            marks = [*fn.decorator_list, *class_marks, *module_marks]
            declared, problems = _marker_problems(marks)
            findings.extend(Finding(rel, fn.lineno, name, p) for p in problems)
            integration = any(_mark_name(m) == "integration" for m in marks)
            if declared or not (integration or scanner.parametrized_integration(mod, fn, cls)):
                continue
            if module_wide is None:
                module_wide = scanner.module_skips(mod) or scanner.autouse_skips(mod)
            if (
                module_wide
                or (
                    scanner.class_skips(mod, cls, class_marks)
                    if cls
                    else scanner.function_setup_skips(mod)
                )
                or scanner.can_skip(mod, fn, as_fixture=False)
                or scanner.requests_skipping_fixture(mod, [*_params(fn), *_usefixtures(marks)], cls)
            ):
                findings.append(Finding(rel, fn.lineno, name, Problem.UNDECLARED))
    return sorted(findings)


def _pytest_config(root: Path) -> tuple[list[str], list[str]]:
    with (root / "pyproject.toml").open("rb") as f:
        options = tomllib.load(f)["tool"]["pytest"]["ini_options"]
    return list(options["testpaths"]), list(options["pythonpath"])


def collected_test_files(root: Path) -> list[Path]:
    """Every test module the repo's pytest collects, plus ``_EXTRA_TEST_DIRS``."""
    testpaths, _ = _pytest_config(root)
    files: set[Path] = set()
    for directory in (*testpaths, *_EXTRA_TEST_DIRS):
        for pattern in ("test_*.py", "*_test.py"):
            files.update(p for p in (root / directory).rglob(pattern) if "fixtures" not in p.parts)
    return sorted(files)


def scan_repo(root: Path) -> list[Finding]:
    _, pythonpath = _pytest_config(root)
    return scan(root, collected_test_files(root), [root / p for p in pythonpath])


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings = scan_repo(root)
    for finding in findings:
        print(finding)
    print(f"{len(findings)} finding(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
