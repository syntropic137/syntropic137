"""Census: integration tests that can skip without saying so (PC-192, PC-193).

A skipped test reports neither pass nor fail. When an integration test skips
because an image defaulted to ``:latest``, a store was not provisioned or an
env var was unset, the job stays green and the test proves nothing. The
mutation-evidence runner caught three of those in one week, by voiding a
baseline with a skip. This module makes the class visible statically.

The rule: a test marked ``integration`` that CAN skip must say so with

    @pytest.mark.may_skip(reason="...", issue="#N")

on the test, its class or its module ``pytestmark``. ``reason`` and ``issue``
are both required, and ``issue`` is a ``#N`` reference, because an opt-out with
no ticket is a skip nobody will come back for.

"Can skip" is decided from the AST, never from text, and follows the paths a
skip actually travels:

- a ``skip``/``skipif`` marker on the test, its class or its module;
- ``pytest.skip`` / ``pytest.importorskip`` in the test body;
- the same calls in a function of the same module the test calls, at any depth
  (``_require(url)`` that skips is the commonest shape here);
- a fixture that skips, requested by parameter, by ``usefixtures`` or by
  ``autouse``, defined in the module or in any ``conftest.py`` between the
  module and the repo root, followed through the fixtures IT requests;
- a module-level ``importorskip`` / ``skip(allow_module_level=True)``.

What it cannot see: a skip in a helper imported from another module, and a
fixture from a plugin. Both are reported as "cannot skip", so the census can
undercount and never overcounts. That is the safe direction for a ratchet whose
budget only goes down: a false positive would push someone to sprinkle
``may_skip`` on tests that cannot skip, which is how an opt-out stops meaning
anything.

The budget lives in ``ci/fitness/fitness_exceptions.toml`` ``[integration_skips]``
and is enforced by ``ci/fitness/code_quality/test_integration_skips_declared.py``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from check_test_markers import is_excluded

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

INTEGRATION_MARKER = "integration"
OPT_OUT_MARKER = "may_skip"

#: Markers that skip by themselves. ``xfail`` is not a skip and is censused by
#: ``check_test_markers``.
_SKIP_MARKERS = frozenset({"skip", "skipif"})

#: ``pytest.<name>(...)`` calls that end the test as skipped.
_SKIP_CALLS = frozenset({"skip", "importorskip"})

#: The ``issue`` argument of the opt-out. Same shape as ``TODO(#N)``.
_ISSUE_PATTERN = re.compile(r"#\d+")

#: Not first-party tests of this repo: the submodules under ``lib/`` are their
#: own repositories with their own gates, on top of the directories
#: ``check_test_markers`` already excludes.
_EXCLUDED_TOP_LEVEL = frozenset({"lib"})


@dataclass(frozen=True)
class Finding:
    """One test the rule applies to, and why.

    ``kind`` is ``undeclared`` (it can skip and has no opt-out, the budgeted
    count) or ``malformed`` (an opt-out without a reason or a ``#N`` issue,
    which is never budgeted: it is new code by definition).
    """

    path: str
    test: str
    kind: Literal["undeclared", "malformed"]
    detail: str

    def render(self) -> str:
        return f"{self.path}::{self.test}: {self.detail}"


# ---------------------------------------------------------------- marker reading


def _mark_name(node: ast.expr) -> str | None:
    """``x`` for ``pytest.mark.x`` or ``pytest.mark.x(...)``, else None."""
    if isinstance(node, ast.Call):
        node = node.func
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
    ):
        return node.attr
    return None


def _pytestmark_marks(body: Iterable[ast.stmt]) -> list[ast.expr]:
    """The marks in a ``pytestmark = <mark> | [<mark>, ...]`` assignment."""
    marks: list[ast.expr] = []
    for stmt in body:
        targets: list[ast.expr] = []
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            continue
        marks.extend(value.elts if isinstance(value, ast.List | ast.Tuple) else [value])
    return marks


def _declaration_error(mark: ast.expr) -> str | None:
    """Why a ``may_skip`` mark does not count as a declaration, or None."""
    keywords = {kw.arg: kw.value for kw in mark.keywords} if isinstance(mark, ast.Call) else {}
    texts = {
        name: value.value.strip()
        for name, value in keywords.items()
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and name
    }
    if not texts.get("reason"):
        return "may_skip needs reason='<why it may skip>' as a non-empty string"
    if not _ISSUE_PATTERN.fullmatch(texts.get("issue", "")):
        return "may_skip needs issue='#N' naming the issue that removes the skip"
    return None


# ---------------------------------------------------------------- skip reachability


def _calls(node: ast.AST) -> Iterator[ast.Call]:
    return (n for n in ast.walk(node) if isinstance(n, ast.Call))


def _called_name(call: ast.Call) -> str | None:
    """``f`` for ``f(...)``, ``self.f(...)`` or ``cls.f(...)``."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in {"self", "cls"}
    ):
        return func.attr
    return None


def _is_skip_call(call: ast.Call, skip_aliases: frozenset[str]) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id == "pytest" and func.attr in _SKIP_CALLS
    return isinstance(func, ast.Name) and func.id in skip_aliases


def _skip_aliases(tree: ast.Module) -> frozenset[str]:
    """Local names bound by ``from pytest import skip [as s], importorskip``."""
    return frozenset(
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "pytest"
        for alias in node.names
        if alias.name in _SKIP_CALLS
    )


def _fixture_decorator(decorator: ast.expr) -> ast.expr | None:
    """The decorator if it is ``@fixture`` / ``@pytest.fixture[(...)]``."""
    func = decorator.func if isinstance(decorator, ast.Call) else decorator
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    return decorator if name == "fixture" else None


def _params(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = func.args
    return [a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]]


def _usefixtures(marks: Iterable[ast.expr]) -> list[str]:
    return [
        arg.value
        for mark in marks
        if isinstance(mark, ast.Call) and _mark_name(mark) == "usefixtures"
        for arg in mark.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]


@dataclass
class _Fixture:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    module: _Module
    autouse: bool


@dataclass
class _Module:
    """One parsed file: its functions by name, its fixtures, its skip vocabulary."""

    rel: str
    tree: ast.Module
    skip_aliases: frozenset[str]
    functions: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = field(default_factory=dict)
    fixtures: dict[str, _Fixture] = field(default_factory=dict)
    _reach: dict[int, str | None] = field(default_factory=dict)

    @classmethod
    def parse(cls, path: Path, rel: str) -> _Module | None:
        try:
            tree = ast.parse(path.read_text(errors="ignore"), filename=rel)
        except SyntaxError:
            return None
        module = cls(rel=rel, tree=tree, skip_aliases=_skip_aliases(tree))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            module.functions.setdefault(node.name, []).append(node)
            for decorator in node.decorator_list:
                fixture = _fixture_decorator(decorator)
                if fixture is None:
                    continue
                kw = {k.arg: k.value for k in getattr(fixture, "keywords", [])}
                name_node = kw.get("name")
                name = (
                    name_node.value
                    if isinstance(name_node, ast.Constant) and isinstance(name_node.value, str)
                    else node.name
                )
                autouse_node = kw.get("autouse")
                autouse = isinstance(autouse_node, ast.Constant) and bool(autouse_node.value)
                module.fixtures[name] = _Fixture(node=node, module=module, autouse=autouse)
        return module

    def body_skips(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
        """Where ``func`` reaches a skip through its own body and same-module calls."""
        key = id(func)
        if key in self._reach:
            return self._reach[key]
        self._reach[key] = None  # recursion guard: a cycle adds no new skip
        found: str | None = None
        for call in _calls(func):
            if _is_skip_call(call, self.skip_aliases):
                found = f"skips at {self.rel}:{call.lineno}"
                break
            callee = _called_name(call)
            for target in self.functions.get(callee or "", []):
                if target is not func and (via := self.body_skips(target)):
                    found = f"calls {callee}(), which {via}"
                    break
            if found:
                break
        self._reach[key] = found
        return found

    def module_level_skip(self) -> str | None:
        for stmt in self.tree.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            for call in _calls(stmt):
                if _is_skip_call(call, self.skip_aliases):
                    return f"module skips at {self.rel}:{call.lineno}"
        return None


class _Scope:
    """The fixtures visible from one test module: its own, then its conftests."""

    def __init__(self, chain: list[_Module]) -> None:
        self._chain = chain  # nearest first

    def lookup(self, name: str) -> _Fixture | None:
        for module in self._chain:
            if name in module.fixtures:
                return module.fixtures[name]
        return None

    def autouse(self) -> list[str]:
        return [n for m in self._chain for n, f in m.fixtures.items() if f.autouse]

    def fixture_skips(self, names: Iterable[str], seen: set[str] | None = None) -> str | None:
        seen = set() if seen is None else seen
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            fixture = self.lookup(name)
            if fixture is None:
                continue
            if via := fixture.module.body_skips(fixture.node):
                return f"fixture '{name}' {via}"
            if via := self.fixture_skips(_params(fixture.node), seen):
                return f"fixture '{name}' requests {via}"
        return None


# ---------------------------------------------------------------- the census


def _test_files(root: Path) -> list[Path]:
    files = {*root.rglob("test_*.py"), *root.rglob("*_test.py")}
    return sorted(
        p
        for p in files
        if not is_excluded(p.relative_to(root))
        and p.relative_to(root).parts[0] not in _EXCLUDED_TOP_LEVEL
    )


class _Census:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._conftests: dict[Path, _Module | None] = {}

    def _conftest(self, directory: Path) -> _Module | None:
        if directory not in self._conftests:
            path = directory / "conftest.py"
            self._conftests[directory] = (
                _Module.parse(path, path.relative_to(self._root).as_posix())
                if path.is_file()
                else None
            )
        return self._conftests[directory]

    def _scope(self, module: _Module, path: Path) -> _Scope:
        chain = [module]
        directory = path.parent
        while True:
            conftest = self._conftest(directory)
            if conftest is not None:
                chain.append(conftest)
            if directory == self._root or self._root not in directory.parents:
                break
            directory = directory.parent
        return _Scope(chain)

    def file_findings(self, path: Path) -> list[Finding]:
        rel = path.relative_to(self._root).as_posix()
        module = _Module.parse(path, rel)
        if module is None:
            return []
        scope = self._scope(module, path)
        module_marks = _pytestmark_marks(module.tree.body)
        findings: list[Finding] = []
        for test, owner_marks in _tests(module.tree):
            marks = [*test.decorator_list, *owner_marks, *module_marks]
            names = {_mark_name(m) for m in marks}
            declarations = [m for m in marks if _mark_name(m) == OPT_OUT_MARKER]
            for declaration in declarations:
                if error := _declaration_error(declaration):
                    findings.append(Finding(rel, test.name, "malformed", error))
            if INTEGRATION_MARKER not in names or declarations:
                continue
            skip_marks = sorted(n for n in names if n in _SKIP_MARKERS)
            via = (
                (f"marked {skip_marks[0]}" if skip_marks else None)
                or module.module_level_skip()
                or module.body_skips(test)
                or scope.fixture_skips([*_params(test), *_usefixtures(marks), *scope.autouse()])
            )
            if via:
                findings.append(Finding(rel, test.name, "undeclared", f"can skip: {via}"))
        return findings


def _tests(
    tree: ast.Module,
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, list[ast.expr]]]:
    """Each collected test function, with the marks its class contributes."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test"):
                yield node, []
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_marks = [*node.decorator_list, *_pytestmark_marks(node.body)]
            for item in node.body:
                if isinstance(
                    item, ast.FunctionDef | ast.AsyncFunctionDef
                ) and item.name.startswith("test"):
                    yield item, class_marks


def find_integration_skips(root: Path) -> list[Finding]:
    """Every integration test under ``root`` that can skip undeclared, and every
    malformed ``may_skip``, in path order."""
    root = root.resolve()
    census = _Census(root)
    return [finding for path in _test_files(root) for finding in census.file_findings(path)]
