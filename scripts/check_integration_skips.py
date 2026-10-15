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

- a ``skip``/``skipif`` marker on the test, its class, its module or one of
  its parameters (``pytest.param(..., marks=...)``);
- ``pytest.skip`` / ``pytest.importorskip`` in the test body;
- the same calls in a function the test calls, at any depth: a bare ``f()``
  reaches module-level functions, ``self.f()`` the methods of the test's own
  class (``_require(url)`` that skips is the commonest shape here);
- a fixture that skips, requested by parameter, by ``usefixtures`` or by
  ``autouse``, defined in the test's class, its module or any ``conftest.py``
  between the module and the repo root, nearest first as pytest resolves it,
  followed through the fixtures IT requests;
- a module-level ``importorskip`` / ``skip(allow_module_level=True)``.

Pytest's names are resolved from the module's imports, so ``import pytest as
pt`` and ``from pytest import mark, skip, param`` read the same as ``pytest.``.

Marks are judged per parameter leg. A test is integration when any leg carries
the marker, whether from a ``parametrize`` value or from the ``params=`` of a
fixture it reaches; a ``may_skip`` on one leg covers that leg only.

What it cannot see: a skip in a helper imported from another module, and a
fixture from a plugin. Both are reported as "cannot skip", so the census can
undercount. It reports reachability, not runtime: a skip behind a condition
counts, because the condition is exactly what fails on a clean runner. It does
not report a skip the test cannot reach - another class's autouse fixture, a
same-named method of another class, a fixture shadowed nearer the test - since
a false positive would push someone to sprinkle ``may_skip`` on tests that
cannot skip, which is how an opt-out stops meaning anything.

The budget lives in ``ci/fitness/fitness_exceptions.toml`` ``[integration_skips]``
and is enforced by ``ci/fitness/code_quality/test_integration_skips_declared.py``.
"""

from __future__ import annotations

import ast
import itertools
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


# ---------------------------------------------------------------- pytest's names


@dataclass(frozen=True)
class _PytestNames:
    """What one module calls pytest's pieces, resolved from its imports.

    ``import pytest as pt`` makes ``pt.mark.x`` a marker and ``pt.skip`` a skip;
    ``from pytest import mark, skip as s, param`` makes ``mark.x``, ``s(...)``
    and ``param(...)`` the same. Markers and skip calls read the same table, so
    a spelling one recognises the other cannot miss.
    """

    modules: frozenset[str]
    mark: frozenset[str]
    skip: frozenset[str]
    param: frozenset[str]

    @classmethod
    def of(cls, tree: ast.Module) -> _PytestNames:
        modules = {"pytest"}
        imported: dict[str, set[str]] = {"mark": set(), "param": set(), "skip": set()}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.asname or a.name for a in node.names if a.name == "pytest")
            elif isinstance(node, ast.ImportFrom) and node.module == "pytest":
                for alias in node.names:
                    kind = "skip" if alias.name in _SKIP_CALLS else alias.name
                    if kind in imported:
                        imported[kind].add(alias.asname or alias.name)
        return cls(
            modules=frozenset(modules),
            mark=frozenset(imported["mark"]),
            skip=frozenset(imported["skip"]),
            param=frozenset(imported["param"]),
        )

    def _is_pytest(self, node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id in self.modules

    def mark_name(self, node: ast.expr) -> str | None:
        """``x`` for ``pytest.mark.x`` or ``pytest.mark.x(...)``, else None."""
        if isinstance(node, ast.Call):
            node = node.func
        if not isinstance(node, ast.Attribute):
            return None
        owner = node.value
        if isinstance(owner, ast.Attribute) and owner.attr == "mark" and self._is_pytest(owner.value):
            return node.attr
        if isinstance(owner, ast.Name) and owner.id in self.mark:
            return node.attr
        return None

    def is_skip_call(self, call: ast.Call) -> bool:
        func = call.func
        if isinstance(func, ast.Attribute):
            return self._is_pytest(func.value) and func.attr in _SKIP_CALLS
        return isinstance(func, ast.Name) and func.id in self.skip

    def is_param(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Attribute):
            return self._is_pytest(func.value) and func.attr == "param"
        return isinstance(func, ast.Name) and func.id in self.param

    def legs(self, values: ast.expr | None) -> list[list[ast.expr]]:
        """The marks each parameter in a literal parameter list carries.

        One entry per parameter, so a mark on one leg never covers another. A
        list that is not a literal is one leg with no marks: what it holds is
        decided at run time.
        """
        if not isinstance(values, ast.List | ast.Tuple):
            return [[]]
        legs: list[list[ast.expr]] = []
        for value in values.elts:
            marks = next(
                (kw.value for kw in getattr(value, "keywords", []) if kw.arg == "marks"),
                None,
            )
            if not self.is_param(value) or marks is None:
                legs.append([])
            elif isinstance(marks, ast.List | ast.Tuple):
                legs.append(list(marks.elts))
            else:
                legs.append([marks])
        return legs or [[]]

    def parametrize_legs(self, marks: Iterable[ast.expr]) -> list[list[list[ast.expr]]]:
        """For each ``parametrize`` mark, the legs of its argvalues."""
        out: list[list[list[ast.expr]]] = []
        for mark in marks:
            if not isinstance(mark, ast.Call) or self.mark_name(mark) != "parametrize":
                continue
            values = next((kw.value for kw in mark.keywords if kw.arg == "argvalues"), None)
            out.append(self.legs(mark.args[1] if len(mark.args) > 1 else values))
        return out

    def usefixtures(self, marks: Iterable[ast.expr]) -> list[str]:
        return [
            arg.value
            for mark in marks
            if isinstance(mark, ast.Call) and self.mark_name(mark) == "usefixtures"
            for arg in mark.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        ]


# ---------------------------------------------------------------- marker reading


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

_Function = ast.FunctionDef | ast.AsyncFunctionDef


def _calls(node: ast.AST) -> Iterator[ast.Call]:
    return (n for n in ast.walk(node) if isinstance(n, ast.Call))


def _fixture_decorator(decorator: ast.expr) -> ast.expr | None:
    """The decorator if it is ``@fixture`` / ``@pytest.fixture[(...)]``."""
    func = decorator.func if isinstance(decorator, ast.Call) else decorator
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    return decorator if name == "fixture" else None


def _params(func: _Function) -> list[str]:
    args = func.args
    return [a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]]


@dataclass
class _Fixture:
    node: _Function
    module: _Module
    #: The class that defines it, whose methods its ``self.x()`` calls reach.
    owner: _Class | None
    autouse: bool
    #: One mark list per value of its ``params=``; empty when it has none.
    legs: list[list[ast.expr]]


@dataclass
class _Class:
    """A ``Test*`` class: what ``self.x()`` and fixture lookup see inside it."""

    node: ast.ClassDef
    methods: dict[str, list[_Function]] = field(default_factory=dict)
    fixtures: dict[str, _Fixture] = field(default_factory=dict)


@dataclass
class _Module:
    """One parsed file, with module and class scope kept apart.

    A bare ``f()`` resolves to a module-level function; ``self.f()`` to a method
    of the class it is written in. A class fixture is visible to that class
    only, so a same-named fixture elsewhere neither shadows nor leaks into it.
    """

    rel: str
    tree: ast.Module
    names: _PytestNames
    functions: dict[str, list[_Function]] = field(default_factory=dict)
    fixtures: dict[str, _Fixture] = field(default_factory=dict)
    classes: dict[str, _Class] = field(default_factory=dict)
    _reach: dict[int, str | None] = field(default_factory=dict)

    @classmethod
    def parse(cls, path: Path, rel: str) -> _Module | None:
        try:
            tree = ast.parse(path.read_text(errors="ignore"), filename=rel)
        except SyntaxError:
            return None
        module = cls(rel=rel, tree=tree, names=_PytestNames.of(tree))
        module._collect(tree.body, module.functions, module.fixtures, None)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                owner = _Class(node)
                module._collect(node.body, owner.methods, owner.fixtures, owner)
                module.classes[node.name] = owner
        return module

    def _collect(
        self,
        body: Iterable[ast.stmt],
        functions: dict[str, list[_Function]],
        fixtures: dict[str, _Fixture],
        owner: _Class | None,
    ) -> None:
        for node in body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            functions.setdefault(node.name, []).append(node)
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
                fixtures[name] = _Fixture(
                    node=node,
                    module=self,
                    owner=owner,
                    autouse=isinstance(autouse_node, ast.Constant) and bool(autouse_node.value),
                    legs=self.names.legs(kw["params"]) if "params" in kw else [],
                )

    def _callees(self, call: ast.Call, owner: _Class | None) -> list[_Function]:
        """What ``f(...)``, ``self.f(...)`` or ``cls.f(...)`` resolves to here."""
        func = call.func
        if isinstance(func, ast.Name):
            return self.functions.get(func.id, [])
        if (
            owner is not None
            and isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in {"self", "cls"}
        ):
            return owner.methods.get(func.attr, [])
        return []

    def body_skips(self, func: _Function, owner: _Class | None) -> str | None:
        """Where ``func`` reaches a skip through its own body and same-scope calls."""
        key = id(func)
        if key in self._reach:
            return self._reach[key]
        self._reach[key] = None  # recursion guard: a cycle adds no new skip
        found: str | None = None
        for call in _calls(func):
            if self.names.is_skip_call(call):
                found = f"skips at {self.rel}:{call.lineno}"
                break
            for target in self._callees(call, owner):
                if target is not func and (via := self.body_skips(target, owner)):
                    found = f"calls {target.name}(), which {via}"
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
                if self.names.is_skip_call(call):
                    return f"module skips at {self.rel}:{call.lineno}"
        return None


class _Scope:
    """The fixtures visible from one test: its class's, its module's, then its
    conftests', nearest first, as pytest resolves them."""

    def __init__(self, layers: list[dict[str, _Fixture]]) -> None:
        self._layers = layers

    def lookup(self, name: str) -> _Fixture | None:
        for layer in self._layers:
            if name in layer:
                return layer[name]
        return None

    def autouse(self) -> list[str]:
        return [n for layer in self._layers for n, f in layer.items() if f.autouse]

    def reached(self, names: Iterable[str]) -> list[tuple[str, _Fixture]]:
        """Every fixture the names request, and the fixtures those request."""
        seen: set[str] = set()
        out: list[tuple[str, _Fixture]] = []
        pending = list(names)
        while pending:
            name = pending.pop(0)
            if name in seen:
                continue
            seen.add(name)
            fixture = self.lookup(name)
            if fixture is not None:
                out.append((name, fixture))
                pending.extend(_params(fixture.node))
        return out

    def fixture_skips(self, names: Iterable[str], seen: set[str] | None = None) -> str | None:
        seen = set() if seen is None else seen
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            fixture = self.lookup(name)
            if fixture is None:
                continue
            if via := fixture.module.body_skips(fixture.node, fixture.owner):
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

    def _conftest_chain(self, path: Path) -> list[_Module]:
        chain: list[_Module] = []
        directory = path.parent
        while True:
            conftest = self._conftest(directory)
            if conftest is not None:
                chain.append(conftest)
            if directory == self._root or self._root not in directory.parents:
                break
            directory = directory.parent
        return chain

    def file_findings(self, path: Path) -> list[Finding]:
        rel = path.relative_to(self._root).as_posix()
        module = _Module.parse(path, rel)
        if module is None:
            return []
        names = module.names
        conftests = [c.fixtures for c in self._conftest_chain(path)]
        module_marks = _pytestmark_marks(module.tree.body)
        findings: list[Finding] = []
        for test, owner in _tests(module):
            class_marks = (
                [*owner.node.decorator_list, *_pytestmark_marks(owner.node.body)] if owner else []
            )
            marks = [*test.decorator_list, *class_marks, *module_marks]
            layers = [*([owner.fixtures] if owner else []), module.fixtures, *conftests]
            scope = _Scope(layers)
            requested = [*_params(test), *names.usefixtures(marks), *scope.autouse()]
            leg_sets = [
                *names.parametrize_legs(marks),
                *(f.legs for _, f in scope.reached(requested) if f.legs),
            ]
            every_mark = [*marks, *(m for legs in leg_sets for leg in legs for m in leg)]
            for declaration in every_mark:
                if names.mark_name(declaration) == OPT_OUT_MARKER and (
                    error := _declaration_error(declaration)
                ):
                    findings.append(Finding(rel, test.name, "malformed", error))
            for combination in itertools.product(*leg_sets):
                leg_marks = [*marks, *(m for leg in combination for m in leg)]
                if via := self._undeclared_skip(module, scope, test, owner, leg_marks, requested):
                    findings.append(Finding(rel, test.name, "undeclared", f"can skip: {via}"))
                    break
        return findings

    @staticmethod
    def _undeclared_skip(
        module: _Module,
        scope: _Scope,
        test: _Function,
        owner: _Class | None,
        marks: list[ast.expr],
        requested: list[str],
    ) -> str | None:
        """How one parameter leg of an integration test skips with no opt-out."""
        marked = {module.names.mark_name(m) for m in marks}
        if INTEGRATION_MARKER not in marked or OPT_OUT_MARKER in marked:
            return None
        skip_marks = sorted(n for n in marked if n in _SKIP_MARKERS)
        return (
            (f"marked {skip_marks[0]}" if skip_marks else None)
            or module.module_level_skip()
            or module.body_skips(test, owner)
            or scope.fixture_skips(requested)
        )


def _tests(module: _Module) -> Iterator[tuple[_Function, _Class | None]]:
    """Each collected test function, with the class it belongs to."""
    for node in module.tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test"):
                yield node, None
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            owner = module.classes[node.name]
            for item in node.body:
                if isinstance(
                    item, ast.FunctionDef | ast.AsyncFunctionDef
                ) and item.name.startswith("test"):
                    yield item, owner


def find_integration_skips(root: Path) -> list[Finding]:
    """Every integration test under ``root`` that can skip undeclared, and every
    malformed ``may_skip``, in path order."""
    root = root.resolve()
    census = _Census(root)
    return [finding for path in _test_files(root) for finding in census.file_findings(path)]
