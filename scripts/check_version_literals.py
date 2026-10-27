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
FastAPI as API``, ``import fastapi as f`` then ``f.FastAPI``, a module alias
(``f = fastapi``), a qualified path (``fastapi.applications.FastAPI``), a
rename by assignment (``API = FastAPI``, chains included) and a subclass
(``class Timed(FastAPI)``). A name that merely ends in ``FastAPI`` and binds to
nothing of the kind does not count.

NAMES ARE RESOLVED PER LEXICAL SCOPE (#2104): module, function, lambda, class
and comprehension, with ``global``/``nonlocal`` honored and a class body
invisible to the functions nested in it. A read sees only the innermost scope
that binds the name, so a parameter or local assignment shadows an outer
import, and an import in one function does not leak into another. Matching the spelling instead would let a
one-line rename dodge the gate and flag unrelated callees, the same failure
``check_untyped_dicts.py`` closed in #1188.

The fitness function ``ci/fitness/code_quality/test_no_hardcoded_version_literals.py``
runs this over the repo and its submodules; ``scripts/tests/test_check_version_literals.py``
pins the detector.
"""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass, field
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


_Comprehension = ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp
_FunctionLike = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
_NO_PATHS: frozenset[str] = frozenset()
# The modules that ``FastAPI`` is reachable from by attribute.
_KNOWN_MODULES = frozenset({_FASTAPI_MODULE, f"{_FASTAPI_MODULE}.applications"})


def _is_module_path(path: str) -> bool:
    """``fastapi`` or a dotted path under it that does not pass the class."""
    return _FASTAPI_CLASS not in path.split(".")


def _is_constructor_path(path: str) -> bool:
    parts = path.split(".")
    return parts[-1] == _FASTAPI_CLASS and _FASTAPI_CLASS not in parts[:-1]


def _is_fastapi_module(name: str) -> bool:
    return name == _FASTAPI_MODULE or name.startswith(f"{_FASTAPI_MODULE}.")


@dataclass(eq=False)
class _Scope:
    """One lexical scope: module, function, lambda, class or comprehension.

    Hashed by identity, so it can key the resolved-value table.
    """

    parent: _Scope | None
    is_class: bool = False
    is_comprehension: bool = False
    bound: set[str] = field(default_factory=set[str])
    declared_global: set[str] = field(default_factory=set[str])
    declared_nonlocal: set[str] = field(default_factory=set[str])

    def module(self) -> _Scope:
        scope = self
        while scope.parent is not None:
            scope = scope.parent
        return scope

    def is_local(self, name: str) -> bool:
        return (
            name in self.bound
            and name not in self.declared_global
            and name not in self.declared_nonlocal
        )


def _owner(scope: _Scope, name: str) -> _Scope | None:
    """The scope a read of ``name`` in ``scope`` resolves to.

    The innermost scope that binds it, honoring ``global`` and ``nonlocal``.
    A class body is visible only to itself, never to the functions, lambdas
    and comprehensions nested in it. ``None`` is a builtin or an unbound name.
    """
    current: _Scope | None = scope
    first = True
    while current is not None:
        if name in current.declared_global:
            return current.module()
        if name in current.declared_nonlocal:
            return _nonlocal_owner(current.parent, name)
        if current.is_local(name) and (first or not current.is_class):
            return current
        first = False
        current = current.parent
    return None


def _owners(scope: _Scope, name: str) -> tuple[_Scope, ...]:
    """Every scope a read of ``name`` in ``scope`` may resolve to.

    ``_owner``, plus one case: a read IN a class body that binds the name may
    still see a binding outside it (``API = API`` reads before the class
    stores its own), so that body falls through as well. Python compiles that
    read as ``LOAD_NAME``, which tries the class, then the MODULE: every
    enclosing function is skipped (#2106). Empty is a builtin or an unbound name.
    """
    owner = _owner(scope, name)
    if owner is None:
        return ()
    if owner is scope and scope.is_class and scope.parent is not None:
        module = scope.module()
        return (owner, module) if module.is_local(name) else (owner,)
    return (owner,)


def _nonlocal_owner(scope: _Scope | None, name: str) -> _Scope | None:
    """The nearest enclosing FUNCTION that binds ``name``: never a class, never the module."""
    current = scope
    while current is not None and current.parent is not None:
        if current.is_local(name) and not current.is_class:
            return current
        current = current.parent
    return None


@dataclass(frozen=True, eq=False)
class _Binding:
    """One store to ``name`` in ``scope``.

    Its value is ``paths`` (an import), what ``alias_of`` resolves to (a
    rename), or the constructor when any of ``bases`` is one (a subclass). A
    binding with none of them still shadows every outer ``name``.
    """

    name: str
    scope: _Scope
    paths: frozenset[str] = _NO_PATHS
    alias_of: ast.expr | None = None
    bases: tuple[ast.expr, ...] = ()

    def owner(self) -> _Scope:
        if self.name in self.scope.declared_global:
            return self.scope.module()
        if self.name in self.scope.declared_nonlocal and self.scope.parent is not None:
            return _nonlocal_owner(self.scope.parent, self.name) or self.scope
        return self.scope


@dataclass(frozen=True)
class _ScopedCall:
    call: ast.Call
    scope: _Scope


def _params(args: ast.arguments) -> list[ast.arg]:
    every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    return [p for p in every if p is not None]


class _ScopeBuilder:
    """One pass over a module: every scope, every binding, every call."""

    def __init__(self) -> None:
        self.module = _Scope(parent=None)
        self.bindings: list[_Binding] = []
        self.calls: list[_ScopedCall] = []

    def _bind(self, binding: _Binding) -> None:
        binding.scope.bound.add(binding.name)
        self.bindings.append(binding)

    def _shadow(self, name: str, scope: _Scope) -> None:
        self._bind(_Binding(name, scope))

    def _visit_function(self, node: _FunctionLike, scope: _Scope) -> None:
        """Defaults, annotations and decorators run in the ENCLOSING scope."""
        outer: list[ast.expr | None] = [*node.args.defaults, *node.args.kw_defaults]
        if not isinstance(node, ast.Lambda):
            outer.extend(node.decorator_list)
            outer.append(node.returns)
            outer.extend(p.annotation for p in _params(node.args))
            self._shadow(node.name, scope)
        for expr in outer:
            if expr is not None:
                self.visit(expr, scope)
        inner = _Scope(parent=scope)
        for param in _params(node.args):
            self._shadow(param.arg, inner)
        body: list[ast.stmt] | list[ast.expr] = (
            [node.body] if isinstance(node, ast.Lambda) else node.body
        )
        for child in body:
            self.visit(child, inner)

    def _visit_class(self, node: ast.ClassDef, scope: _Scope) -> None:
        for expr in [*node.decorator_list, *node.bases, *node.keywords]:
            self.visit(expr, scope)
        inner = _Scope(parent=scope, is_class=True)
        for stmt in node.body:
            self.visit(stmt, inner)
        self._bind(_Binding(node.name, scope, bases=tuple(node.bases)))

    def _visit_comprehension(self, node: _Comprehension, scope: _Scope) -> None:
        inner = _Scope(parent=scope, is_comprehension=True)
        for index, gen in enumerate(node.generators):
            # The first iterable is evaluated in the enclosing scope.
            self.visit(gen.iter, scope if index == 0 else inner)
            self.visit(gen.target, inner)
            for cond in gen.ifs:
                self.visit(cond, inner)
        results = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        for expr in results:
            self.visit(expr, inner)

    def _visit_import(self, node: ast.Import | ast.ImportFrom, scope: _Scope) -> None:
        for alias in node.names:
            if alias.name == "*":
                continue
            paths = _NO_PATHS
            if isinstance(node, ast.Import):
                # ``import a.b`` binds ``a``; ``import a.b as c`` binds ``c`` to ``a.b``.
                name = alias.asname or alias.name.split(".")[0]
                target = alias.name if alias.asname else name
                if _is_fastapi_module(target):
                    paths = frozenset({target})
            else:
                name = alias.asname or alias.name
                if node.level == 0 and node.module and _is_fastapi_module(node.module):
                    paths = frozenset({f"{node.module}.{alias.name}"})
            self._bind(_Binding(name, scope, paths=paths))

    def _visit_assignment(
        self, node: ast.Assign | ast.AnnAssign | ast.NamedExpr, scope: _Scope
    ) -> None:
        if node.value is not None:
            self.visit(node.value, scope)
        if isinstance(node, ast.AnnAssign):
            self.visit(node.annotation, scope)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        # A walrus in a comprehension binds in the nearest enclosing scope
        # that is not a comprehension.
        owner = scope
        while isinstance(node, ast.NamedExpr) and owner.is_comprehension and owner.parent:
            owner = owner.parent
        for target in targets:
            if isinstance(target, ast.Name):
                self._bind(_Binding(target.id, owner, alias_of=node.value))
            else:
                self.visit(target, scope)

    def _visit_other(self, node: ast.AST, scope: _Scope) -> None:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            self._shadow(node.id, scope)
        elif isinstance(node, ast.Global):
            scope.declared_global.update(node.names)
        elif isinstance(node, ast.Nonlocal):
            scope.declared_nonlocal.update(node.names)
        elif isinstance(node, ast.Call):
            self.calls.append(_ScopedCall(node, scope))
        elif isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and node.name:
            self._shadow(node.name, scope)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            self._shadow(node.rest, scope)
        for child in ast.iter_child_nodes(node):
            self.visit(child, scope)

    def visit(self, node: ast.AST, scope: _Scope) -> None:
        if isinstance(node, _FunctionLike):
            self._visit_function(node, scope)
        elif isinstance(node, ast.ClassDef):
            self._visit_class(node, scope)
        elif isinstance(node, _Comprehension):
            self._visit_comprehension(node, scope)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            self._visit_import(node, scope)
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr):
            self._visit_assignment(node, scope)
        else:
            self._visit_other(node, scope)


@dataclass(frozen=True)
class _Resolution:
    """What each (scope, name) is bound to, as dotted paths under ``fastapi``."""

    values: Mapping[tuple[_Scope, str], frozenset[str]]

    def paths(self, node: ast.expr, scope: _Scope) -> frozenset[str]:
        if isinstance(node, ast.Name):
            return _NO_PATHS.union(
                *(self.values.get((owner, node.id), _NO_PATHS) for owner in _owners(scope, node.id))
            )
        if isinstance(node, ast.Attribute):
            extended = (
                f"{path}.{node.attr}"
                for path in self.paths(node.value, scope)
                if _is_module_path(path)
            )
            # A finite domain, so the fixpoint terminates: ``f = f.applications``
            # would otherwise grow ``fastapi.applications.applications...`` forever.
            return frozenset(
                path for path in extended if path in _KNOWN_MODULES or _is_constructor_path(path)
            )
        return _NO_PATHS

    def is_constructor(self, node: ast.expr, scope: _Scope) -> bool:
        return any(_is_constructor_path(path) for path in self.paths(node, scope))

    def binding_paths(self, binding: _Binding) -> frozenset[str]:
        if binding.alias_of is not None:
            return self.paths(binding.alias_of, binding.scope)
        if any(self.is_constructor(base, binding.scope) for base in binding.bases):
            return frozenset({f"{_FASTAPI_MODULE}.{_FASTAPI_CLASS}"})
        return binding.paths


def _resolve(builder: _ScopeBuilder) -> _Resolution:
    """Propagate imports through renames and subclasses to a fixpoint.

    Flow-insensitive WITHIN a scope (a name counts when any of its bindings
    there reaches FastAPI, since which one runs first cannot be known
    statically) but exact ACROSS scopes: a read sees only the innermost scope
    that binds the name, so a parameter or local assignment shadows an outer
    import and an import in one function is invisible to another.
    """
    for binding in builder.bindings:
        # ``global``/``nonlocal`` make a store bind in an outer scope.
        binding.owner().bound.add(binding.name)
    values: dict[tuple[_Scope, str], frozenset[str]] = {}
    changed = True
    while changed:
        changed = False
        resolution = _Resolution(values)
        for binding in builder.bindings:
            key = (binding.owner(), binding.name)
            old = values.get(key, _NO_PATHS)
            new = old | resolution.binding_paths(binding)
            if new != old:
                values[key] = new
                changed = True
    return _Resolution(values)


def violations(source: str, filename: str = "<string>") -> list[Finding]:
    """Every hardcoded release number in ``source``."""
    tree = ast.parse(source, filename)
    found = [
        Finding(stmt.lineno, DUNDER)
        for stmt in module_scope_statements(tree.body)
        if _binds_literal_dunder(stmt)
    ]
    builder = _ScopeBuilder()
    for stmt in tree.body:
        builder.visit(stmt, builder.module)
    resolution = _resolve(builder)
    found.extend(
        Finding(scoped.call.lineno, FASTAPI)
        for scoped in builder.calls
        if resolution.is_constructor(scoped.call.func, scoped.scope)
        and any(k.arg == "version" and _is_str_literal(k.value) for k in scoped.call.keywords)
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
