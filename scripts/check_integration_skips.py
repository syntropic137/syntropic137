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

- a ``skip``/``skipif`` mark on the test, its class or its module;
- a call to ``pytest.skip`` or ``pytest.importorskip`` in the test, in its
  module's top level, or in any function it calls that resolves to a
  module-level function here or imported by name from a repo module;
- a fixture that does any of the above: requested as a parameter, through
  ``usefixtures``, or autouse in the module or a ``conftest.py`` above it.
  Fixture parameters are followed the same way.

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


def _is_fixture(fn: _Fn) -> tuple[bool, bool]:
    """(is a fixture, is autouse)."""
    for dec in fn.decorator_list:
        if _dotted(dec).split(".")[-1] in _FIXTURE_DECORATORS:
            autouse = isinstance(dec, ast.Call) and any(
                kw.arg == "autouse"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in dec.keywords
            )
            return True, autouse
    return False, False


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


@dataclass
class _Module:
    path: Path
    tree: ast.Module
    functions: dict[str, _Fn]
    fixtures: dict[str, _Fn]
    autouse: list[_Fn]
    imports: dict[str, tuple[str, str]]  # local name -> (module, name)
    pytest_skip_names: frozenset[str]  # bare names bound to pytest.skip/importorskip

    @property
    def marks(self) -> list[ast.expr]:
        return _pytestmark(self.tree.body)


class Scanner:
    """Parses modules once and answers "can this function skip?" across them."""

    def __init__(self, root: Path, import_roots: Sequence[Path]) -> None:
        self.root = root
        self._import_roots = [root, *import_roots]
        self._modules: dict[Path, _Module | None] = {}
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
        fixtures: dict[str, _Fn] = {}
        autouse: list[_Fn] = []
        imports: dict[str, tuple[str, str]] = {}
        skip_names: set[str] = set()
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[stmt.name] = stmt
                is_fixture, is_autouse = _is_fixture(stmt)
                if is_fixture:
                    fixtures[stmt.name] = stmt
                    if is_autouse:
                        autouse.append(stmt)
            elif isinstance(stmt, ast.ImportFrom):
                base = self._resolve_relative(path, stmt)
                for alias in stmt.names:
                    local = alias.asname or alias.name
                    if stmt.module == "pytest" and alias.name in _SKIP_CALLS:
                        skip_names.add(local)
                    elif base:
                        imports[local] = (base, alias.name)
        return _Module(path, tree, functions, fixtures, autouse, imports, frozenset(skip_names))

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
        if module.startswith("/"):
            candidates = [Path(module[1:])]
        else:
            rel = module.replace(".", "/")
            candidates = [r / rel for r in self._import_roots]
        for base in candidates:
            for path in (base.with_suffix(".py"), base / "__init__.py"):
                if path.is_file():
                    return path
        return None

    def _resolve(self, mod: _Module, name: str, table: str) -> tuple[_Module, _Fn] | None:
        """A function or fixture named ``name`` as seen from ``mod``."""
        found = (mod.fixtures if table == "fixtures" else mod.functions).get(name)
        if found is not None:
            return mod, found
        if name in mod.imports:
            target_module, target_name = mod.imports[name]
            target_path = self._import_target(target_module)
            target = self.module(target_path) if target_path else None
            if target is not None:
                found = (target.fixtures if table == "fixtures" else target.functions).get(
                    target_name
                )
                if found is not None:
                    return target, found
        return None

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

    def _fixture(self, mod: _Module, name: str) -> tuple[_Module, _Fn] | None:
        found = self._resolve(mod, name, "fixtures")
        if found is not None:
            return found
        for conftest in self._conftests(mod.path):
            found = self._resolve(conftest, name, "fixtures")
            if found is not None:
                return found
        return None

    # -- the question -------------------------------------------------------

    def marks_skip(self, marks: Iterable[ast.expr]) -> bool:
        return any(_mark_name(m) in _SKIP_MARKS for m in marks)

    def _calls_skip(self, mod: _Module, nodes: Iterable[ast.AST]) -> list[str]:
        """Whether ``nodes`` call a skip directly; else the bare names they call."""
        called: list[str] = []
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            name = _dotted(node.func)
            if name.startswith("pytest.") and name.split(".", 1)[1] in _SKIP_CALLS:
                return ["<skip>"]
            if name in mod.pytest_skip_names:
                return ["<skip>"]
            if isinstance(node.func, ast.Name):
                called.append(node.func.id)
        return called

    def module_skips(self, mod: _Module) -> bool:
        """Importing the module can skip it, or every test in it is skip-marked."""
        if self.marks_skip(mod.marks):
            return True
        return self._calls_skip(mod, _module_level_nodes(mod.tree.body)) == ["<skip>"]

    def can_skip(self, mod: _Module, fn: _Fn, *, as_fixture: bool) -> bool:
        key = (mod.path, f"{'fixture' if as_fixture else 'fn'}:{fn.name}:{fn.lineno}")
        if key in self._skips:
            return self._skips[key]
        self._skips[key] = False  # cycle guard: a recursion is not a skip
        result = self._can_skip(mod, fn, as_fixture=as_fixture)
        self._skips[key] = result
        return result

    def _can_skip(self, mod: _Module, fn: _Fn, *, as_fixture: bool) -> bool:
        if self.marks_skip(fn.decorator_list):
            return True
        called = self._calls_skip(mod, _own_nodes(fn))
        if called == ["<skip>"]:
            return True
        for name in called:
            found = self._resolve(mod, name, "functions")
            if found is not None and self.can_skip(*found, as_fixture=False):
                return True
        if as_fixture:
            return self.requests_skipping_fixture(mod, _params(fn))
        return False

    def requests_skipping_fixture(self, mod: _Module, names: Iterable[str]) -> bool:
        for name in names:
            found = self._fixture(mod, name)
            if found is not None and self.can_skip(*found, as_fixture=True):
                return True
        return False

    def parametrized_integration(self, mod: _Module, fn: _Fn, seen: set[int] | None = None) -> bool:
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
            found = self._fixture(mod, name)
            if found is not None and self.parametrized_integration(*found, seen):
                return True
        return False

    def autouse_skips(self, mod: _Module) -> bool:
        for owner in (mod, *self._conftests(mod.path)):
            if any(self.can_skip(owner, fn, as_fixture=True) for fn in owner.autouse):
                return True
        return False


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


def _tests(tree: ast.Module) -> Iterator[tuple[str, _Fn, list[ast.expr]]]:
    """(qualified name, function, class-level marks) for each collected test."""
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith(
            "test"
        ):
            yield stmt.name, stmt, []
        elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
            class_marks = [*stmt.decorator_list, *_pytestmark(stmt.body)]
            for item in stmt.body:
                if isinstance(
                    item, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and item.name.startswith("test"):
                    yield f"{stmt.name}::{item.name}", item, class_marks


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
        for name, fn, class_marks in _tests(mod.tree):
            marks = [*fn.decorator_list, *class_marks, *module_marks]
            declared, problems = _marker_problems(marks)
            findings.extend(Finding(rel, fn.lineno, name, p) for p in problems)
            integration = any(_mark_name(m) == "integration" for m in marks)
            if declared or not (integration or scanner.parametrized_integration(mod, fn)):
                continue
            if module_wide is None:
                module_wide = scanner.module_skips(mod) or scanner.autouse_skips(mod)
            if (
                module_wide
                or scanner.marks_skip(class_marks)
                or scanner.can_skip(mod, fn, as_fixture=False)
                or scanner.requests_skipping_fixture(mod, [*_params(fn), *_usefixtures(marks)])
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
