"""Fitness: production code cannot construct an in-memory adapter (ADR-060).

ADR-060 says every in-memory adapter is guarded: constructing one outside a
test or offline environment raises ``InMemoryAdapterError``. The guard is
``syn_shared.in_memory`` -- inherit ``InMemoryAdapter``, or call
``assert_test_only()`` from ``__init__``/``__post_init__``. Until this test the
rule was convention only, and the convention had already been broken.

**What counts as an in-memory adapter.** A class in a production module
(``apps/*/src``, ``packages/*/src``, not ``test_*.py``) that either

- is named ``InMemory*``, ``Memory*``, ``Fake*`` or ``Stub*`` (followed by an
  upper-case letter, so ``Memoryless`` is not one), or
- lives in a module whose file name contains ``memory`` or ``fake`` and names
  a port among its bases -- a ``Protocol`` declared in a ``ports`` package or
  a ``*_port.py`` module, or any base whose name ends in ``Port``.
- is named, by exact ``"<path>::<ClassName>"`` key, in ``_NAMED_CANDIDATES``:
  in-process state that matches neither pattern but must still be accounted
  for in the exceptions table (ADR-072 D8's ``RunTodoStore``).

The second rule exists so that renaming ``InMemoryFooStore`` to ``FooStore``
does not walk it out of the gate (the #1188 lesson: a gate keyed on spelling
alone is dodged by a rename). It cannot see a port implemented structurally,
without naming it as a base; that needs type information an AST scan lacks.
``Protocol`` declarations themselves are never candidates.

**What counts as guarded.** Constructing the class provably runs
``assert_test_only()``. The scan follows what Python does, not how the code is
spelled:

- ``__init__`` is found along the class's C3 MRO. It runs the guard if a
  top-level statement of its body calls it with no ``return`` before; a call
  inside ``if``/``try``/a loop/a nested function is a path that skips it. If it
  does not, it passes the question on only through an equally unconditional
  ``super().__init__()``, to the next class in the MRO.
- ``__post_init__`` counts only when a ``@dataclass``-generated ``__init__`` is
  the one found, because nothing else calls it. It is searched from the start
  of the MRO, as ``self.__post_init__`` is, and chains through
  ``super().__post_init__()`` the same way.
- The call must resolve to the guard: ``assert_test_only`` imported unrenamed
  from ``syn_shared.in_memory`` or its re-export ``syn_adapters.in_memory``
  (in the module or the method), or ``<alias>.assert_test_only()`` on an
  import of one of those modules, and not rebound anywhere else in that scope.
  ``InMemoryAdapter`` is guarded by exactly this rule.
- A base resolves to the class of that name in the same module, else to the
  only production class of that name. An ambiguous or non-production base
  (other than ``object``/``ABC``/``Generic``/``Protocol``) is opaque: reaching
  it before the guard means the guard is not proven.

Anything outside these shapes reads as unguarded. That is the safe failure: a
false alarm is fixed by writing the guard plainly, a false pass is the bug.
``test_scanner_verdict_matches_runtime`` constructs every pinned shape against
a raising guard, so each verdict is checked against Python itself.

**Which files.** Every production module, package ``__init__.py`` included:
a class declared there is as constructible as one anywhere else.

**Exceptions.** ``[in_memory_adapters_guarded]`` in ``fitness_exceptions.toml``,
keyed ``"<path>::<ClassName>"`` with a ``reason``. Use it for a class that
matches the rule but is not an adapter, or for a known violation with an
``issue`` that fixes it. An entry that no longer matches an unguarded
candidate fails the test, so the table can only shrink.

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
import textwrap
import types
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_ADAPTER_NAME = re.compile(r"^(InMemory|Memory|Fake|Stub)[A-Z]")
_ADAPTER_MODULE_WORDS = ("memory", "fake")
_GUARD_CALL = "assert_test_only"
_INIT = "__init__"
_POST_INIT = "__post_init__"
_EXCEPTIONS_SECTION = "in_memory_adapters_guarded"
#: Classes that hold in-process state but match neither pattern, named so the
#: gate sees them and the exceptions table must say why each is allowed. Exact
#: keys only: a pattern here would exempt classes nobody has reasoned about.
#: ``RunTodoStore`` is ADR-072 D8's run-scoped to-do cache, rebuilt from durable
#: events at every claim; naming it means a guard added to it later (which
#: would refuse production and break every run) fails the stale-exception check.
_NAMED_CANDIDATES = frozenset(
    {
        "packages/syn-domain/src/syn_domain/contexts/orchestration/slices/"
        "execute_workflow/run_todo_fold.py::RunTodoStore",
    }
)


#: Modules a guard may be imported from: the definition and its re-export.
_GUARD_MODULES = frozenset({"syn_shared.in_memory", "syn_adapters.in_memory"})
_GUARD_DEFINED_IN = ("syn_shared", "in_memory.py")  # trailing path parts
#: Unresolved bases known to contribute no __init__ / __post_init__.
_INERT_BASES = frozenset({"object", "ABC", "Generic", "Protocol"})

_Fn = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class _ClassInfo:
    key: str  # "<path>::<ClassName>", the exceptions-table key
    name: str
    line: int
    path: Path
    base_names: tuple[str, ...]
    is_candidate: bool
    is_dataclass: bool
    init: _Fn | None
    post_init: _Fn | None
    module_guard_names: frozenset[str]  # bare names bound to the guard here
    module_guard_aliases: frozenset[str]  # dotted names bound to a guard module


@dataclass(frozen=True)
class Candidate:
    key: str
    line: int
    guarded: bool


def _simple_name(expr: ast.expr) -> str:
    """``mod.Foo[int]`` -> ``Foo``: the name a base is resolved by."""
    if isinstance(expr, ast.Subscript):
        return _simple_name(expr.value)
    if isinstance(expr, ast.Attribute):
        return expr.attr
    if isinstance(expr, ast.Name):
        return expr.id
    return ""


def _dotted(expr: ast.expr) -> str:
    if isinstance(expr, ast.Attribute):
        head = _dotted(expr.value)
        return f"{head}.{expr.attr}" if head else ""
    return expr.id if isinstance(expr, ast.Name) else ""


def _method(node: ast.ClassDef, name: str) -> _Fn | None:
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
            return item
    return None


def _scope_nodes(body: list[ast.stmt]) -> list[ast.AST]:
    """Every node in ``body`` that executes in this scope, not in a nested one."""
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        found.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue  # its name binds here; its body does not run here
        stack.extend(ast.iter_child_nodes(node))
    return found


def _bound_names(node: ast.AST) -> list[tuple[str, ast.AST]]:
    """The names ``node`` binds in its own scope, each with the binding node."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [(node.name, node)]
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return [(node.id, node)]
    if isinstance(node, ast.arg):
        return [(node.arg, node)]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [((a.asname or a.name).split(".")[0], node) for a in node.names]
    return []


def _guard_names(body: list[ast.stmt], *, defines_guard: bool) -> tuple[set[str], set[str]]:
    """Names in this scope that can only mean the guard, and guard-module aliases.

    A name counts only if EVERY binding of it in the scope binds the guard, so
    a later ``def assert_test_only`` or assignment shadows the import away.
    """
    bindings: dict[str, list[ast.AST]] = {}
    for node in _scope_nodes(body):
        for name, binder in _bound_names(node):
            bindings.setdefault(name, []).append(binder)

    def binds_guard(binder: ast.AST) -> bool:
        if isinstance(binder, ast.FunctionDef) and defines_guard:
            return binder.name == _GUARD_CALL
        return (
            isinstance(binder, ast.ImportFrom)
            and binder.module in _GUARD_MODULES
            and any(a.name == _GUARD_CALL and a.asname is None for a in binder.names)
        )

    def binds_module(binder: ast.AST, name: str) -> str | None:
        if isinstance(binder, ast.Import):
            for a in binder.names:
                if a.asname == name and a.name in _GUARD_MODULES:
                    return name
                if a.asname is None and a.name.split(".")[0] == name and a.name in _GUARD_MODULES:
                    return a.name
        if isinstance(binder, ast.ImportFrom) and binder.module:
            for a in binder.names:
                if (a.asname or a.name) == name and f"{binder.module}.{a.name}" in _GUARD_MODULES:
                    return name
        return None

    names = {n for n, bs in bindings.items() if n == _GUARD_CALL and all(map(binds_guard, bs))}
    aliases: set[str] = set()
    for name, binders in bindings.items():
        dotted = {binds_module(b, name) for b in binders}
        if None not in dotted:
            aliases |= {d for d in dotted if d is not None}
    return names, aliases


def _always_runs(fn: _Fn, match: Callable[[ast.Call], bool]) -> bool:
    """A top-level statement of ``fn`` is a matching call, with no return before it.

    Anything weaker -- the call inside an ``if``, a ``try``, a loop, a nested
    function, or after an early ``return`` -- is a path that skips it.
    """
    for stmt in fn.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and match(stmt.value):
            return True
        if any(isinstance(n, ast.Return) for n in _scope_nodes([stmt])):
            return False
    return False


def _runs_guard(fn: _Fn | None, info: _ClassInfo) -> bool:
    if fn is None:
        return False
    local_names, local_aliases = _guard_names(fn.body, defines_guard=False)
    local_bound = {n for node in _scope_nodes([*fn.body]) for n, _ in _bound_names(node)}
    local_bound |= {a.arg for a in ast.walk(fn.args) if isinstance(a, ast.arg)}
    names = local_names | (set(info.module_guard_names) - local_bound)
    aliases = local_aliases | {
        a for a in info.module_guard_aliases if a.split(".")[0] not in local_bound
    }

    def is_guard(call: ast.Call) -> bool:
        if isinstance(call.func, ast.Name):
            return call.func.id in names
        if isinstance(call.func, ast.Attribute) and call.func.attr == _GUARD_CALL:
            return _dotted(call.func.value) in aliases
        return False

    return _always_runs(fn, is_guard)


def _calls_super(fn: _Fn | None, method: str) -> bool:
    if fn is None:
        return False

    def is_super(call: ast.Call) -> bool:
        func = call.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr == method
            and isinstance(func.value, ast.Call)
            and _simple_name(func.value.func) == "super"
        )

    return _always_runs(fn, is_super)


def _is_protocol(node: ast.ClassDef) -> bool:
    return any(_simple_name(base) == "Protocol" for base in node.bases)


def _is_dataclass(node: ast.ClassDef) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if _simple_name(target) == "dataclass":
            return True
    return False


def _is_port_module(path: Path) -> bool:
    return "ports" in path.parts or path.stem.endswith("_port")


def _parse(files: list[Path]) -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))) for path in files
    ]


def _port_names(modules: list[tuple[Path, ast.Module]]) -> set[str]:
    return {
        node.name
        for path, tree in modules
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and _is_protocol(node)
        and (_is_port_module(path) or node.name.endswith("Port"))
    }


def _class_info(
    path: Path,
    node: ast.ClassDef,
    ports: set[str],
    root: Path,
    guards: tuple[set[str], set[str]],
) -> _ClassInfo:
    base_names = tuple(_simple_name(base) for base in node.bases)
    in_adapter_module = any(word in path.stem.lower() for word in _ADAPTER_MODULE_WORDS)
    names_a_port = any(name in ports or name.endswith("Port") for name in base_names)
    key = f"{rel_path(path, root)}::{node.name}"
    is_candidate = not _is_protocol(node) and (
        bool(_ADAPTER_NAME.match(node.name))
        or (in_adapter_module and names_a_port)
        or key in _NAMED_CANDIDATES
    )
    return _ClassInfo(
        key=key,
        name=node.name,
        line=node.lineno,
        path=path,
        base_names=base_names,
        is_candidate=is_candidate,
        is_dataclass=_is_dataclass(node),
        init=_method(node, _INIT),
        post_init=_method(node, _POST_INIT),
        module_guard_names=frozenset(guards[0]),
        module_guard_aliases=frozenset(guards[1]),
    )


class _Resolver:
    """Resolves bases by name and walks Python's C3 MRO over them.

    A base resolves to the class of that name in the same module, else to the
    only production class of that name. Anything else -- ambiguous, or not a
    production class -- is opaque: it may define ``__init__``, so reaching it
    before a guard means the guard is not proven to run.
    """

    def __init__(self, classes: list[_ClassInfo]) -> None:
        self._by_name: dict[str, list[_ClassInfo]] = {}
        for info in classes:
            self._by_name.setdefault(info.name, []).append(info)
        self._mro: dict[str, list[_ClassInfo | str] | None] = {}

    def _base(self, owner: _ClassInfo, name: str) -> _ClassInfo | str:
        definitions = self._by_name.get(name, [])
        local = [d for d in definitions if d.path == owner.path and d is not owner]
        if len(local) == 1:
            return local[0]
        if len(definitions) == 1 and definitions[0] is not owner:
            return definitions[0]
        return name  # opaque

    def mro(
        self, info: _ClassInfo, visiting: frozenset[str] = frozenset()
    ) -> list[_ClassInfo | str] | None:
        if info.key in self._mro:
            return self._mro[info.key]
        if info.key in visiting:
            return None
        seqs: list[list[_ClassInfo | str]] = []
        bases = [self._base(info, n) for n in info.base_names]
        for base in bases:
            if isinstance(base, str):
                seqs.append([base])
                continue
            sub = self.mro(base, visiting | {info.key})
            if sub is None:
                self._mro[info.key] = None
                return None
            seqs.append(list(sub))
        seqs.append(list(bases))
        result: list[_ClassInfo | str] = [info]
        while any(seqs):
            seqs = [s for s in seqs if s]
            head = next((s[0] for s in seqs if not any(s[0] in t[1:] for t in seqs)), None)
            if head is None:
                self._mro[info.key] = None  # no consistent MRO: Python refuses it too
                return None
            result.append(head)
            seqs = [s[1:] if s[0] is head or s[0] == head else s for s in seqs]
        self._mro[info.key] = result
        return result


def _guarded(info: _ClassInfo, resolver: _Resolver) -> bool:
    """Constructing ``info`` provably runs the guard, following Python's MRO."""
    mro = resolver.mro(info)
    if mro is None:
        return False

    def from_hook(start: int, hook: str) -> bool:
        for cls in mro[start:]:
            if isinstance(cls, str):
                if cls in _INERT_BASES:
                    continue
                return False  # opaque base: its hook is unknown
            fn = cls.init if hook == _INIT else cls.post_init
            generated_init = hook == _INIT and fn is None and cls.is_dataclass
            if generated_init:
                # The generated __init__ calls self.__post_init__, looked up
                # from the instance's own type, and never calls super().__init__.
                return from_hook(0, _POST_INIT)
            if fn is None:
                continue
            if _runs_guard(fn, cls):
                return True
            return _calls_super(fn, hook) and from_hook(mro.index(cls) + 1, hook)
        return False

    return from_hook(0, _INIT)


def scan(files: list[Path], root: Path) -> list[Candidate]:
    """Every in-memory adapter candidate in ``files``, and whether it is guarded."""
    modules = _parse(files)
    ports = _port_names(modules)
    classes: list[_ClassInfo] = []
    for path, tree in modules:
        defines_guard = path.parts[-len(_GUARD_DEFINED_IN) :] == _GUARD_DEFINED_IN
        guards = _guard_names(tree.body, defines_guard=defines_guard)
        classes += [
            _class_info(path, node, ports, root, guards)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        ]
    resolver = _Resolver(classes)
    return [
        Candidate(key=info.key, line=info.line, guarded=_guarded(info, resolver))
        for info in classes
        if info.is_candidate
    ]


def find_violations(root: Path) -> list[str]:
    """Unguarded, unexcepted candidates across every production module under ``root``."""
    exceptions = load_exceptions(root).get(_EXCEPTIONS_SECTION, {})
    files = production_files(root, include_package_inits=True)
    return [
        f"  {c.key} (line {c.line})"
        for c in scan(files, root)
        if not c.guarded and c.key not in exceptions
    ]


@pytest.mark.architecture
class TestInMemoryAdaptersAreGuarded:
    def test_every_in_memory_adapter_is_guarded(self) -> None:
        violations = find_violations(repo_root())
        assert not violations, (
            "In-memory adapters constructible in production (ADR-060). Inherit "
            "InMemoryAdapter, or call assert_test_only() in __init__/__post_init__ "
            "(syn_shared.in_memory). If the class is not an adapter, add it to "
            f"[{_EXCEPTIONS_SECTION}] in ci/fitness/fitness_exceptions.toml with a "
            "reason:\n" + "\n".join(violations)
        )

    def test_exceptions_are_live_and_explained(self) -> None:
        root = repo_root()
        exceptions = load_exceptions(root).get(_EXCEPTIONS_SECTION, {})
        files = production_files(root, include_package_inits=True)
        unguarded = {c.key for c in scan(files, root) if not c.guarded}

        stale = sorted(set(exceptions) - unguarded)
        assert not stale, (
            "These exceptions no longer name an unguarded candidate (fixed, renamed "
            f"or deleted). Remove them from [{_EXCEPTIONS_SECTION}]:\n  " + "\n  ".join(stale)
        )
        unexplained = sorted(k for k, v in exceptions.items() if not v.get("reason"))
        assert not unexplained, f"Exceptions without a reason: {unexplained}"


#: Stands in for syn_shared.in_memory, which the real scan sees among the
#: production files. Without it a fixture's base would be unresolvable and every
#: inheritance case would read "unguarded" for the wrong reason.
_GUARD_MODULE = """
class InMemoryAdapterError(Exception): ...

def assert_test_only() -> None:
    raise InMemoryAdapterError

class InMemoryAdapter:
    def __init__(self) -> None:
        assert_test_only()
"""


def _scan_source(tmp_path: Path, source: str, name: str = "store.py") -> dict[str, bool]:
    guard = tmp_path / "syn_shared" / "in_memory.py"
    guard.parent.mkdir(exist_ok=True)
    guard.write_text(_GUARD_MODULE, encoding="utf-8")
    module = tmp_path / name
    module.write_text(textwrap.dedent(source), encoding="utf-8")
    return {
        c.key.split("::")[1]: c.guarded
        for c in scan([guard, module], tmp_path)
        if c.key.startswith(name)
    }


@pytest.mark.architecture
class TestScanner:
    """Pins the detection and guard rules, so the gate cannot quietly go blind."""

    def test_unguarded_in_memory_class_fails(self, tmp_path: Path) -> None:
        assert _scan_source(tmp_path, "class InMemoryFoo:\n    pass\n") == {"InMemoryFoo": False}

    def test_inheriting_through_a_guarded_base_passes(self, tmp_path: Path) -> None:
        result = _scan_source(
            tmp_path,
            """
            from syn_shared.in_memory import InMemoryAdapter

            class _Base(InMemoryAdapter):
                pass

            class InMemoryFoo(_Base):
                def __init__(self) -> None:
                    super().__init__()
            """,
        )
        assert result == {"InMemoryFoo": True}

    def test_assert_test_only_in_post_init_passes(self, tmp_path: Path) -> None:
        result = _scan_source(
            tmp_path,
            """
            from dataclasses import dataclass
            from syn_shared.in_memory import assert_test_only

            @dataclass
            class FakeClock:
                def __post_init__(self) -> None:
                    assert_test_only()
            """,
        )
        assert result == {"FakeClock": True}

    def test_init_without_super_drops_the_inherited_guard(self, tmp_path: Path) -> None:
        result = _scan_source(
            tmp_path,
            """
            class MemoryFoo(InMemoryAdapter):
                def __init__(self) -> None:
                    self.items = {}

            class MemoryBar(InMemoryAdapter):
                def __init__(self) -> None:
                    super().__init__()
                    self.items = {}
            """,
        )
        assert result == {"MemoryFoo": False, "MemoryBar": True}

    def test_dataclass_drops_a_guard_inherited_through_init(self, tmp_path: Path) -> None:
        result = _scan_source(
            tmp_path,
            """
            from dataclasses import dataclass

            @dataclass
            class StubFoo(InMemoryAdapter):
                items: int = 0

            class StubBar(InMemoryAdapter):
                items: int = 0
            """,
        )
        assert result == {"StubFoo": False, "StubBar": True}

    def test_unresolvable_base_is_not_a_guard(self, tmp_path: Path) -> None:
        assert _scan_source(tmp_path, "class InMemoryFoo(SomethingElse):\n    pass\n") == {
            "InMemoryFoo": False
        }

    def test_renamed_port_implementation_in_a_memory_module_is_caught(self, tmp_path: Path) -> None:
        result = _scan_source(
            tmp_path,
            """
            class FooStore(StorePort):
                pass

            class Helper:
                pass
            """,
            name="memory_store.py",
        )
        assert result == {"FooStore": False}

    def test_protocols_and_non_matching_names_are_not_candidates(self, tmp_path: Path) -> None:
        result = _scan_source(
            tmp_path,
            """
            from typing import Protocol

            class InMemoryStoreProtocol(Protocol):
                pass

            class Memoryless:
                pass
            """,
        )
        assert result == {}


def _constructs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> bool:
    """Whether ``InMemoryFoo()`` succeeds at runtime when the guard always raises."""
    import syn_shared

    guard = types.ModuleType("syn_shared.in_memory")
    exec(_GUARD_MODULE, guard.__dict__)  # fixed source above
    monkeypatch.setitem(sys.modules, "syn_shared.in_memory", guard)
    monkeypatch.setattr(syn_shared, "in_memory", guard, raising=False)
    path = tmp_path / "runtime_store.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("runtime_store", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.InMemoryFoo()
    except guard.InMemoryAdapterError:
        return False
    return True


_IMPORT = "from dataclasses import dataclass\nfrom syn_shared.in_memory import InMemoryAdapter, assert_test_only\n"

#: (id, source defining InMemoryFoo, guarded). Each is also constructed at
#: runtime against a raising guard, so a verdict here is the behaviour, not
#: the spelling.
_SHAPES = [
    # Verification of #1551 found each unguarded shape reported guarded.
    (
        "guard-under-if-false",
        "class InMemoryFoo:\n    def __init__(self):\n        if False:\n            assert_test_only()\n",
        False,
    ),
    (
        "guard-in-nested-function",
        "class InMemoryFoo:\n    def __init__(self):\n        def later():\n            assert_test_only()\n",
        False,
    ),
    (
        "guard-after-early-return",
        "class InMemoryFoo:\n    def __init__(self):\n        if True:\n            return\n        assert_test_only()\n",
        False,
    ),
    (
        "guard-swallowed-by-try",
        "class InMemoryFoo:\n    def __init__(self):\n        try:\n            assert_test_only()\n        except Exception:\n            pass\n",
        False,
    ),
    (
        "guard-shadowed-locally",
        "class InMemoryFoo:\n    def __init__(self):\n        assert_test_only = print\n        assert_test_only()\n",
        False,
    ),
    (
        "guard-shadowed-in-module",
        "def assert_test_only():\n    pass\n\nclass InMemoryFoo:\n    def __init__(self):\n        assert_test_only()\n",
        False,
    ),
    (
        "unrelated-same-named-call",
        "class audit:\n    @staticmethod\n    def assert_test_only():\n        pass\n\nclass InMemoryFoo:\n    def __init__(self):\n        audit.assert_test_only()\n",
        False,
    ),
    (
        "post-init-without-dataclass",
        "class InMemoryFoo:\n    def __post_init__(self):\n        assert_test_only()\n",
        False,
    ),
    (
        "mro-plain-init-before-adapter",
        "class _Plain:\n    def __init__(self):\n        pass\n\nclass InMemoryFoo(_Plain, InMemoryAdapter):\n    pass\n",
        False,
    ),
    (
        "dataclass-post-init-without-super",
        "@dataclass\nclass _Base:\n    def __post_init__(self):\n        assert_test_only()\n\n@dataclass\nclass InMemoryFoo(_Base):\n    def __post_init__(self):\n        pass\n",
        False,
    ),
    # Shapes that really do run the guard.
    (
        "guard-in-init",
        "class InMemoryFoo:\n    def __init__(self):\n        self.x = 1\n        assert_test_only()\n",
        True,
    ),
    (
        "dataclass-post-init",
        "@dataclass\nclass InMemoryFoo:\n    def __post_init__(self):\n        assert_test_only()\n",
        True,
    ),
    (
        "dataclass-inherits-post-init",
        "@dataclass\nclass _Base:\n    def __post_init__(self):\n        assert_test_only()\n\n@dataclass\nclass InMemoryFoo(_Base):\n    pass\n",
        True,
    ),
    (
        "mro-adapter-first",
        "class _Plain:\n    def __init__(self):\n        pass\n\nclass InMemoryFoo(InMemoryAdapter, _Plain):\n    pass\n",
        True,
    ),
    (
        "mro-cooperative-super",
        "class _Plain:\n    def __init__(self):\n        super().__init__()\n\nclass InMemoryFoo(_Plain, InMemoryAdapter):\n    pass\n",
        True,
    ),
    (
        "guard-imported-in-function",
        "class InMemoryFoo:\n    def __init__(self):\n        from syn_shared.in_memory import assert_test_only\n        assert_test_only()\n",
        True,
    ),
    (
        "guard-via-module-alias",
        "from syn_shared import in_memory\n\nclass InMemoryFoo:\n    def __init__(self):\n        in_memory.assert_test_only()\n",
        True,
    ),
]


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("source", "guarded"), [s[1:] for s in _SHAPES], ids=[s[0] for s in _SHAPES]
)
def test_scanner_verdict_matches_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, guarded: bool
) -> None:
    source = _IMPORT + source
    assert _scan_source(tmp_path, source) == {"InMemoryFoo": guarded}
    assert _constructs(tmp_path, monkeypatch, source) is not guarded


@pytest.mark.architecture
def test_adapter_in_a_package_init_fails_the_whole_codebase_gate(tmp_path: Path) -> None:
    package_init = tmp_path / "packages" / "x" / "src" / "x" / "__init__.py"
    package_init.parent.mkdir(parents=True)
    package_init.write_text("class InMemoryFoo:\n    pass\n", encoding="utf-8")

    assert find_violations(tmp_path) == ["  packages/x/src/x/__init__.py::InMemoryFoo (line 1)"]
    # Other gates keep measuring modules only.
    assert production_files(tmp_path) == []
