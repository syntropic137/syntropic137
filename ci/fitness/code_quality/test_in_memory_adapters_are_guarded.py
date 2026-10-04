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

The second rule exists so that renaming ``InMemoryFooStore`` to ``FooStore``
does not walk it out of the gate (the #1188 lesson: a gate keyed on spelling
alone is dodged by a rename). It cannot see a port implemented structurally,
without naming it as a base; that needs type information an AST scan lacks.
``Protocol`` declarations themselves are never candidates.

**What counts as guarded.** Its own ``__init__`` or ``__post_init__`` calls
``assert_test_only()``, or it inherits from a guarded class -- ``InMemoryAdapter``
itself is guarded this way -- without discarding that guard. A guard inherited
through ``__init__`` is discarded by a subclass that defines ``__init__``
without calling ``super().__init__()``, and by a ``@dataclass`` subclass, whose
generated ``__init__`` never calls the base's. A guard inherited through
``__post_init__`` is discarded by a ``__post_init__`` that does not call
``super().__post_init__()``. Bases are resolved by class name across every
production module; when a name is defined more than once, every definition
must be guarded.

**Exceptions.** ``[in_memory_adapters_guarded]`` in ``fitness_exceptions.toml``,
keyed ``"<path>::<ClassName>"`` with a ``reason``. Use it for a class that
matches the rule but is not an adapter, or for a known violation with an
``issue`` that fixes it. An entry that no longer matches an unguarded
candidate fails the test, so the table can only shrink.

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

_ADAPTER_NAME = re.compile(r"^(InMemory|Memory|Fake|Stub)[A-Z]")
_ADAPTER_MODULE_WORDS = ("memory", "fake")
_GUARD_CALL = "assert_test_only"
_INIT = "__init__"
_POST_INIT = "__post_init__"
_EXCEPTIONS_SECTION = "in_memory_adapters_guarded"


@dataclass(frozen=True)
class _ClassInfo:
    key: str  # "<path>::<ClassName>", the exceptions-table key
    name: str
    line: int
    base_names: tuple[str, ...]
    is_candidate: bool
    own_guard: str | None  # the hook that calls assert_test_only, if any
    init_drops_super: bool  # replaces __init__ without reaching the base's
    post_init_drops_super: bool


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


def _method(node: ast.ClassDef, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
            return item
    return None


def _calls(fn: ast.AST | None, name: str) -> bool:
    if fn is None:
        return False
    return any(
        isinstance(call, ast.Call) and _simple_name(call.func) == name for call in ast.walk(fn)
    )


def _calls_super(fn: ast.AST | None, method: str) -> bool:
    if fn is None:
        return False
    for call in ast.walk(fn):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
            continue
        receiver = call.func.value
        if (
            call.func.attr == method
            and isinstance(receiver, ast.Call)
            and _simple_name(receiver.func) == "super"
        ):
            return True
    return False


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


def _class_info(path: Path, node: ast.ClassDef, ports: set[str], root: Path) -> _ClassInfo:
    base_names = tuple(_simple_name(base) for base in node.bases)
    in_adapter_module = any(word in path.stem.lower() for word in _ADAPTER_MODULE_WORDS)
    names_a_port = any(name in ports or name.endswith("Port") for name in base_names)
    is_candidate = not _is_protocol(node) and (
        bool(_ADAPTER_NAME.match(node.name)) or (in_adapter_module and names_a_port)
    )

    init = _method(node, _INIT)
    post_init = _method(node, _POST_INIT)
    own_guard = _INIT if _calls(init, _GUARD_CALL) else None
    if own_guard is None and _calls(post_init, _GUARD_CALL):
        own_guard = _POST_INIT

    if init is not None:
        init_drops_super = not _calls_super(init, _INIT)
    else:
        init_drops_super = _is_dataclass(node)

    return _ClassInfo(
        key=f"{rel_path(path, root)}::{node.name}",
        name=node.name,
        line=node.lineno,
        base_names=base_names,
        is_candidate=is_candidate,
        own_guard=own_guard,
        init_drops_super=init_drops_super,
        post_init_drops_super=post_init is not None and not _calls_super(post_init, _POST_INIT),
    )


def scan(files: list[Path], root: Path) -> list[Candidate]:
    """Every in-memory adapter candidate in ``files``, and whether it is guarded."""
    modules = _parse(files)
    ports = _port_names(modules)
    classes = [
        _class_info(path, node, ports, root)
        for path, tree in modules
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]
    by_name: dict[str, list[_ClassInfo]] = {}
    for info in classes:
        by_name.setdefault(info.name, []).append(info)

    hooks: dict[str, str | None] = {}

    def hook_of(info: _ClassInfo, visiting: frozenset[str]) -> str | None:
        """The hook through which constructing ``info`` runs the guard, or None."""
        if info.key in hooks:
            return hooks[info.key]
        if info.key in visiting:
            return None
        hook = info.own_guard
        for base in info.base_names:
            if hook is not None:
                break
            definitions = by_name.get(base, [])
            base_hooks = {hook_of(d, visiting | {info.key}) for d in definitions}
            if not definitions or None in base_hooks or len(base_hooks) != 1:
                continue
            (inherited,) = base_hooks
            dropped = info.init_drops_super if inherited == _INIT else info.post_init_drops_super
            hook = None if dropped else inherited
        hooks[info.key] = hook
        return hook

    return [
        Candidate(key=info.key, line=info.line, guarded=hook_of(info, frozenset()) is not None)
        for info in classes
        if info.is_candidate
    ]


@pytest.mark.architecture
class TestInMemoryAdaptersAreGuarded:
    def test_every_in_memory_adapter_is_guarded(self) -> None:
        root = repo_root()
        exceptions = load_exceptions(root).get(_EXCEPTIONS_SECTION, {})
        unguarded = [c for c in scan(production_files(root), root) if not c.guarded]

        violations = [f"  {c.key} (line {c.line})" for c in unguarded if c.key not in exceptions]
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
        unguarded = {c.key for c in scan(production_files(root), root) if not c.guarded}

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
def assert_test_only() -> None: ...

class InMemoryAdapter:
    def __init__(self) -> None:
        assert_test_only()
"""


def _scan_source(tmp_path: Path, source: str, name: str = "store.py") -> dict[str, bool]:
    guard = tmp_path / "guard.py"
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
