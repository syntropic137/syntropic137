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

Parameter marks count too: ``pytest.param(..., marks=...)`` in a
``parametrize`` or a fixture's ``params`` gives one leg of the test its own
``integration``, ``skipif`` or ``may_skip``, and each leg is judged on its own
marks. Names are resolved where pytest resolves them: a class's fixtures and
``self.`` methods belong to that class, a fixture that requests its own name
reaches the next scope out, and ``import pytest as pt`` / ``from pytest import
mark, skip`` are one vocabulary for markers and skip calls alike.

What it cannot see: a skip in a helper imported from another module, a fixture
from a plugin, and marks built dynamically. Those are reported as "cannot
skip", so the census undercounts there. It also cannot tell which parameter a
fixture body's ``if request.param == ...`` branch belongs to, so a skip in a
parametrized fixture's body is charged to every integration leg that fixture
has. Both errors are deliberate trade-offs, not guarantees: a false positive
pushes someone to put ``may_skip`` on a test that cannot skip, which is how an
opt-out stops meaning anything, so keep the census as close to pytest as the
AST allows.

The budget lives in ``ci/fitness/fitness_exceptions.toml`` ``[integration_skips]``
and is enforced by ``ci/fitness/code_quality/test_integration_skips_declared.py``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from itertools import product
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
    """How one module spells pytest: ``import pytest [as pt]`` binds the module,
    ``from pytest import mark [as m], skip [as s], param`` binds its members.

    Markers, skip calls and ``pytest.param`` are all resolved through this one
    table, so an alias that works for one works for all of them.
    """

    modules: frozenset[str]
    members: tuple[tuple[str, str], ...]  # (local name, pytest attribute)

    @classmethod
    def of(cls, tree: ast.Module) -> _PytestNames:
        modules = {"pytest"}
        members: list[tuple[str, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.asname or a.name for a in node.names if a.name == "pytest")
            elif isinstance(node, ast.ImportFrom) and node.module == "pytest":
                members.extend((a.asname or a.name, a.name) for a in node.names)
        return cls(modules=frozenset(modules), members=tuple(members))

    def refers_to(self, node: ast.expr, attributes: frozenset[str]) -> bool:
        """``node`` is ``pytest.<a>`` (any module alias) or a name bound to ``<a>``."""
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return node.value.id in self.modules and node.attr in attributes
        if isinstance(node, ast.Name):
            return any(local == node.id and attr in attributes for local, attr in self.members)
        return False

    def mark_name(self, node: ast.expr) -> str | None:
        """``x`` for ``pytest.mark.x[(...)]`` or ``mark.x[(...)]``, else None."""
        if isinstance(node, ast.Call):
            node = node.func
        if isinstance(node, ast.Attribute) and self.refers_to(node.value, _MARK):
            return node.attr
        return None

    def is_skip_call(self, call: ast.Call) -> bool:
        return self.refers_to(call.func, _SKIP_CALLS)


_MARK = frozenset({"mark"})
_PARAM = frozenset({"param"})


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
        marks.extend(_listed(value))
    return marks


def _listed(value: ast.expr) -> list[ast.expr]:
    return list(value.elts) if isinstance(value, ast.List | ast.Tuple) else [value]


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


#: One parameter leg: the marks ``pytest.param(..., marks=...)`` gives it.
_Leg = tuple[ast.expr, ...]


def _legs(values: ast.expr | None, names: _PytestNames) -> list[_Leg]:
    """The legs of a ``params=[...]`` / parametrize argvalues list.

    A value that is not a literal list has no marks pytest can see statically,
    so it is one unmarked leg.
    """
    if not isinstance(values, ast.List | ast.Tuple):
        return [()]
    legs: list[_Leg] = []
    for value in values.elts:
        marks: _Leg = ()
        if isinstance(value, ast.Call) and names.refers_to(value.func, _PARAM):
            for kw in value.keywords:
                if kw.arg == "marks":
                    marks = tuple(_listed(kw.value))
        legs.append(marks)
    return legs or [()]


def _parametrize_legs(marks: Iterable[ast.expr], names: _PytestNames) -> list[list[_Leg]]:
    """One list of legs per ``parametrize`` mark among ``marks``."""
    sources: list[list[_Leg]] = []
    for mark in marks:
        if not isinstance(mark, ast.Call) or names.mark_name(mark) != "parametrize":
            continue
        values = mark.args[1] if len(mark.args) > 1 else None
        for kw in mark.keywords:
            if kw.arg == "argvalues":
                values = kw.value
        sources.append(_legs(values, names))
    return sources


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


def _usefixtures(marks: Iterable[ast.expr], names: _PytestNames) -> list[str]:
    return [
        arg.value
        for mark in marks
        if isinstance(mark, ast.Call) and names.mark_name(mark) == "usefixtures"
        for arg in mark.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]


def _functions(body: Iterable[ast.stmt]) -> list[_Function]:
    return [s for s in body if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef)]


@dataclass
class _Fixture:
    name: str
    node: _Function
    module: _Module
    autouse: bool
    legs: list[_Leg] | None  # None when the fixture is not parametrized


def _fixtures(functions: Iterable[_Function], module: _Module) -> dict[str, _Fixture]:
    """The fixtures among ``functions``, keyed by the name a test requests."""
    found: dict[str, _Fixture] = {}
    for node in functions:
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
            legs = _legs(kw["params"], module.names) if "params" in kw else None
            found[name] = _Fixture(name, node, module, autouse, legs)
    return found


@dataclass
class _Module:
    """One parsed file, with every name kept at the scope that defines it.

    Module functions resolve bare calls; a class's methods (and those of its
    same-module bases) resolve ``self.``/``cls.`` calls made inside that class;
    a class's fixtures are visible only to that class's tests.
    """

    rel: str
    tree: ast.Module
    names: _PytestNames
    functions: dict[str, list[_Function]] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    fixtures: dict[str, _Fixture] = field(default_factory=dict)
    _owner: dict[int, ast.ClassDef] = field(default_factory=dict)
    _class_fixtures: dict[int, dict[str, _Fixture]] = field(default_factory=dict)
    _reach: dict[int, str | None] = field(default_factory=dict)

    @classmethod
    def parse(cls, path: Path, rel: str) -> _Module | None:
        try:
            tree = ast.parse(path.read_text(errors="ignore"), filename=rel)
        except SyntaxError:
            return None
        module = cls(rel=rel, tree=tree, names=_PytestNames.of(tree))
        for node in _functions(tree.body):
            module.functions.setdefault(node.name, []).append(node)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                module.classes[node.name] = node
                for method in _functions(node.body):
                    module._owner[id(method)] = node
        module.fixtures = _fixtures(_functions(tree.body), module)
        return module

    def class_fixtures(self, owner: ast.ClassDef) -> dict[str, _Fixture]:
        if id(owner) not in self._class_fixtures:
            self._class_fixtures[id(owner)] = _fixtures(_functions(owner.body), self)
        return self._class_fixtures[id(owner)]

    def _methods(self, owner: ast.ClassDef, name: str) -> list[_Function]:
        """``name`` as ``self.name`` sees it from ``owner``: its own, then its bases'."""
        own = [f for f in _functions(owner.body) if f.name == name]
        if own:
            return own
        for base in owner.bases:
            parent = self.classes.get(base.id) if isinstance(base, ast.Name) else None
            if (
                parent is not None
                and parent is not owner
                and (found := self._methods(parent, name))
            ):
                return found
        return []

    def _callees(self, func: _Function, call: ast.Call) -> list[_Function]:
        target = call.func
        if isinstance(target, ast.Name):
            return self.functions.get(target.id, [])
        owner = self._owner.get(id(func))
        if (
            owner is not None
            and isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id in {"self", "cls"}
        ):
            return self._methods(owner, target.attr)
        return []

    def body_skips(self, func: _Function) -> str | None:
        """Where ``func`` reaches a skip through its own body and same-module calls."""
        key = id(func)
        if key in self._reach:
            return self._reach[key]
        self._reach[key] = None  # recursion guard: a cycle adds no new skip
        found: str | None = None
        for call in _calls(func):
            if self.names.is_skip_call(call):
                found = f"skips at {self.rel}:{call.lineno}"
                break
            for target in self._callees(func, call):
                if target is not func and (via := self.body_skips(target)):
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
    conftests', nearest first. A fixture that requests its own name reaches the
    next level out, as pytest's overrides do."""

    def __init__(self, levels: list[dict[str, _Fixture]]) -> None:
        self._levels = levels  # nearest first

    def _lookup(self, name: str, start: int = 0) -> tuple[int, _Fixture] | None:
        for level in range(start, len(self._levels)):
            if name in self._levels[level]:
                return level, self._levels[level][name]
        return None

    def autouse(self) -> list[str]:
        return [n for level in self._levels for n, f in level.items() if f.autouse]

    def _requests(self, fixture: _Fixture, level: int) -> Iterator[tuple[str, int]]:
        for name in _params(fixture.node):
            yield name, (level + 1 if name == fixture.name else 0)

    def fixture_skips(
        self,
        requests: Iterable[tuple[str, int]],
        seen: set[tuple[str, int]] | None = None,
    ) -> str | None:
        seen = set() if seen is None else seen
        for name, start in requests:
            if (name, start) in seen:
                continue
            seen.add((name, start))
            found = self._lookup(name, start)
            if found is None:
                continue
            level, fixture = found
            if via := fixture.module.body_skips(fixture.node):
                return f"fixture '{name}' {via}"
            if via := self.fixture_skips(self._requests(fixture, level), seen):
                return f"fixture '{name}' requests {via}"
        return None

    def closure(self, requests: Iterable[tuple[str, int]]) -> list[_Fixture]:
        """Every fixture the requests reach, each once."""
        reached: dict[int, _Fixture] = {}
        pending = list(requests)
        seen: set[tuple[str, int]] = set()
        while pending:
            request = pending.pop()
            if request in seen:
                continue
            seen.add(request)
            if (found := self._lookup(*request)) is None:
                continue
            level, fixture = found
            reached[id(fixture.node)] = fixture
            pending.extend(self._requests(fixture, level))
        return list(reached.values())


# ---------------------------------------------------------------- the census


def _test_files(root: Path) -> list[Path]:
    files = {*root.rglob("test_*.py"), *root.rglob("*_test.py")}
    return sorted(
        p
        for p in files
        if not is_excluded(p.relative_to(root))
        and p.relative_to(root).parts[0] not in _EXCLUDED_TOP_LEVEL
    )


@dataclass(frozen=True)
class _Test:
    """One collected test function and the marks it inherits from outside it."""

    node: _Function
    owner: ast.ClassDef | None
    owner_marks: list[ast.expr]

    @property
    def node_id(self) -> str:
        return f"{self.owner.name}::{self.node.name}" if self.owner else self.node.name


def _tests(tree: ast.Module) -> Iterator[_Test]:
    """Each collected test function, with the marks its class contributes."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test"):
                yield _Test(node, None, [])
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_marks = [*node.decorator_list, *_pytestmark_marks(node.body)]
            for item in _functions(node.body):
                if item.name.startswith("test"):
                    yield _Test(item, node, class_marks)


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

    def _conftest_levels(self, path: Path) -> list[dict[str, _Fixture]]:
        levels: list[dict[str, _Fixture]] = []
        directory = path.parent
        while True:
            conftest = self._conftest(directory)
            if conftest is not None:
                levels.append(conftest.fixtures)
            if directory == self._root or self._root not in directory.parents:
                break
            directory = directory.parent
        return levels

    def file_findings(self, path: Path) -> list[Finding]:
        rel = path.relative_to(self._root).as_posix()
        module = _Module.parse(path, rel)
        if module is None:
            return []
        conftests = self._conftest_levels(path)
        module_marks = _pytestmark_marks(module.tree.body)
        findings: list[Finding] = []
        for test in _tests(module.tree):
            own = [module.class_fixtures(test.owner)] if test.owner else []
            scope = _Scope([*own, module.fixtures, *conftests])
            findings.extend(self._test_findings(rel, module, scope, test, module_marks))
        return findings

    def _test_findings(
        self,
        rel: str,
        module: _Module,
        scope: _Scope,
        test: _Test,
        module_marks: list[ast.expr],
    ) -> list[Finding]:
        names = module.names
        static = [*test.node.decorator_list, *test.owner_marks, *module_marks]
        requests = [
            (name, 0)
            for name in [*_params(test.node), *_usefixtures(static, names), *scope.autouse()]
        ]
        sources = [
            *_parametrize_legs(static, names),
            *(f.legs for f in scope.closure(requests) if f.legs is not None),
        ]
        legs = [tuple(m for leg in combo for m in leg) for combo in product(*sources)]

        findings: list[Finding] = []
        reported: set[int] = set()
        for mark in [*static, *(m for leg in legs for m in leg)]:
            if names.mark_name(mark) == OPT_OUT_MARKER and id(mark) not in reported:
                reported.add(id(mark))
                if error := _declaration_error(mark):
                    findings.append(Finding(rel, test.node_id, "malformed", error))

        reachable: str | None = None
        for index, leg in enumerate(legs):
            marked = {names.mark_name(m) for m in [*static, *leg]}
            if INTEGRATION_MARKER not in marked or OPT_OUT_MARKER in marked:
                continue
            skip_marks = sorted(n for n in marked if n in _SKIP_MARKERS)
            if not skip_marks and reachable is None:
                reachable = (
                    module.module_level_skip()
                    or module.body_skips(test.node)
                    or scope.fixture_skips(requests)
                    or ""
                )
            via = f"marked {skip_marks[0]}" if skip_marks else reachable
            if via:
                where = f" (parameter set {index})" if len(legs) > 1 else ""
                findings.append(Finding(rel, test.node_id, "undeclared", f"can skip{where}: {via}"))
                break
        return findings


def find_integration_skips(root: Path) -> list[Finding]:
    """Every integration test under ``root`` that can skip undeclared, and every
    malformed ``may_skip``, in path order."""
    root = root.resolve()
    census = _Census(root)
    return [finding for path in _test_files(root) for finding in census.file_findings(path)]
