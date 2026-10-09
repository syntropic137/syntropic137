"""Fitness function: every workspace-hardening setting has a production consumer (#1805).

`SYN_SECURITY_*` documented six workspace limits for over a year and provisioning
read none of them. An operator who set `SYN_SECURITY_MAX_PIDS` got pids 256 from
agentic_isolation's `SecurityConfig.production()`, no error, and a
`.env.example` that still promised the setting worked. #1606 deleted two of its
fields for the same reason and left four behind, because nothing measured the
rest.

So this measures it. For every Settings class in `syn_shared.settings` whose
env prefix is in GOVERNED_PREFIXES, each field must be read by production code:
an attribute read in a non-test module outside `syn_shared/settings` whose
receiver is identifiably an instance of the class (see `settings_reads`). The
receiver is what separates `settings.memory_limit_mb` from some other object's
`memory_limit_mb`; mentioning the class name in the same file is not enough.

Fields that are known to be inert are listed in `fitness_exceptions.toml`
under `[workspace_settings_consumed]` with an issue. The list is exact: a field
that gains a consumer must leave it, so it can only shrink.

The check is a static proxy. It proves something reads the field, not that
the value reaches the container; the env-to-argv tests beside each limit
(`test_workspace_limits.py`) prove that hop.

Principle: 8. Fitness functions (docs/architecture/architectural-fitness.md)
Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from functools import cache

import pytest
from ci.fitness.conftest import load_exceptions, production_files, rel_path
from pydantic_settings import BaseSettings

pytestmark = [pytest.mark.unit, pytest.mark.architecture]

#: Env prefixes whose settings shape a workspace container. A class that is
#: added under one of these, including a revived SYN_SECURITY_*, is governed.
GOVERNED_PREFIXES = ("SYN_SECURITY_", "SYN_WORKSPACE_")

_SETTINGS_DIR = "packages/syn-shared/src/syn_shared/settings/"


def _governed_settings() -> list[type[BaseSettings]]:
    import syn_shared.settings as package

    found: dict[str, type[BaseSettings]] = {}
    for info in pkgutil.iter_modules(package.__path__, f"{package.__name__}."):
        module = importlib.import_module(info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if not issubclass(cls, BaseSettings) or cls is BaseSettings:
                continue
            prefix = cls.model_config.get("env_prefix", "")
            if prefix in GOVERNED_PREFIXES:
                found[f"{cls.__module__}.{cls.__qualname__}"] = cls
    return [found[k] for k in sorted(found)]


def _settings_accessors(cls: type[BaseSettings]) -> frozenset[str]:
    """Properties on the root `Settings` that return an instance of `cls`.

    `get_settings().workspace` is a `WorkspaceSettings`; a read through that
    property is a read on the settings instance like any other.
    """
    from syn_shared.settings.config import Settings

    names: set[str] = set()
    for name, member in inspect.getmembers(Settings, lambda m: isinstance(m, property)):
        # Annotations are unevaluated strings here (`from __future__ import
        # annotations`, TYPE_CHECKING-only imports), so match the spelling.
        returns = getattr(member.fget, "__annotations__", {}).get("return")
        if returns in (cls, cls.__name__):
            names.add(name)
    return frozenset(names)


def _names_class(node: ast.AST | None, class_name: str) -> bool:
    """True when an annotation spells `class_name`, bare, dotted, quoted or in a union."""
    if node is None:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == class_name:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == class_name:
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            try:
                quoted = ast.parse(sub.value, mode="eval")
            except SyntaxError:
                continue  # a Literal["..."] value, not a quoted annotation
            if _names_class(quoted, class_name):
                return True
    return False


def _constructs(node: ast.AST | None, class_name: str) -> bool:
    """True for `Cls(...)` or `module.Cls(...)`."""
    return isinstance(node, ast.Call) and _names_class(node.func, class_name)


def _instance_names(scope: ast.AST, class_name: str) -> set[str]:
    """Names bound to a `class_name` instance directly inside `scope`.

    A parameter annotated with the class, `x = Cls()`, or `x: Cls = ...`.
    Nested functions are their own scope and are not descended into.
    """
    names: set[str] = set()
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        args = scope.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if _names_class(arg.annotation, class_name):
                names.add(arg.arg)
    for node in _own_nodes(scope):
        if isinstance(node, ast.Assign) and _constructs(node.value, class_name):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and (_names_class(node.annotation, class_name) or _constructs(node.value, class_name))
        ):
            names.add(node.target.id)
    return names


def _own_nodes(scope: ast.AST) -> list[ast.AST]:
    """Every node in `scope` that is not inside a nested function or class."""
    out: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        out.append(node)
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            stack.extend(ast.iter_child_nodes(node))
    return out


def settings_reads(source: str, class_name: str, accessors: frozenset[str]) -> set[str]:
    """Attributes read on a `class_name` instance in `source`.

    The receiver must be identifiably the settings instance: a name bound to
    it in the same scope or the module, `Cls().field`, or
    `<root settings>.<accessor>.field`. An attribute of the same name on any
    other object is not a read of the setting, and neither is a comment or
    docstring that mentions the class (#1805 verify B2).
    """
    tree = ast.parse(source)
    module_names = _instance_names(tree, class_name)
    scopes: list[ast.AST] = [tree]
    scopes += [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda)
    ]
    reads: set[str] = set()
    for scope in scopes:
        local = _instance_names(scope, class_name) if scope is not tree else set()
        bound = module_names | local
        for node in _own_nodes(scope):
            if not (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)):
                continue
            receiver = node.value
            if (
                (isinstance(receiver, ast.Name) and receiver.id in bound)
                or _constructs(receiver, class_name)
                or (isinstance(receiver, ast.Attribute) and receiver.attr in accessors)
            ):
                reads.add(node.attr)
    return reads


@cache
def _consumed_attributes(cls: type[BaseSettings]) -> frozenset[str]:
    """Fields read on a `cls` instance by production code outside the settings package."""
    accessors = _settings_accessors(cls)
    attrs: set[str] = set()
    for path in production_files():
        if rel_path(path).startswith(_SETTINGS_DIR):
            continue
        source = path.read_text(encoding="utf-8")
        attrs.update(settings_reads(source, cls.__name__, accessors))
    return frozenset(attrs)


def _unconsumed() -> set[str]:
    dead: set[str] = set()
    for cls in _governed_settings():
        consumed = _consumed_attributes(cls)
        dead.update(f"{cls.__name__}.{name}" for name in cls.model_fields if name not in consumed)
    return dead


def _allowed() -> dict[str, str]:
    section = load_exceptions().get("workspace_settings_consumed", {})
    return {key: entry["issue"] for key, entry in section.items()}


@pytest.mark.architecture
class TestWorkspaceSettingsConsumed:
    def test_governed_classes_are_found(self) -> None:
        # Guards against the scan going vacuous: if discovery broke, every
        # other assertion here would pass on an empty set.
        names = {cls.__name__ for cls in _governed_settings()}
        assert "WorkspaceSettings" in names, names

    def test_every_governed_setting_has_a_consumer(self) -> None:
        new_dead = sorted(_unconsumed() - set(_allowed()))
        assert not new_dead, (
            "These settings are documented in .env.example but no production module "
            f"reads them: {new_dead}. Wire each into the code that provisions the "
            "workspace (WorkspaceServiceConfig.from_settings for limits), or delete it "
            "and run `just gen-env gen-compose`. A setting nobody reads tells operators "
            "they have a control they do not have (#1805)."
        )

    def test_exceptions_are_not_stale(self) -> None:
        stale = sorted(set(_allowed()) - _unconsumed())
        assert not stale, (
            f"{stale} now have a production consumer, or no longer exist. Remove them "
            "from [workspace_settings_consumed] in ci/fitness/fitness_exceptions.toml."
        )

    def test_security_prefix_is_gone(self) -> None:
        # SYN_SECURITY_* was deleted rather than wired (#1805): workspace
        # hardening is SecurityConfig.production() in agentic_isolation, and
        # an env var must not be able to loosen it. Reviving the prefix needs
        # a decision, not a field.
        revived = [
            cls.__name__
            for cls in _governed_settings()
            if cls.model_config.get("env_prefix") == "SYN_SECURITY_"
        ]
        assert not revived, revived


_RECEIVER_FIXTURE = '''
from syn_shared.settings.workspace import WorkspaceSettings

# WorkspaceSettings.second_limit is mentioned here, in a comment, and must not count.


def build(settings: WorkspaceSettings, config: object) -> tuple[object, object]:
    """WorkspaceSettings.second_limit in a docstring does not count either."""
    return settings.first_limit, config.second_limit


def unrelated(event: object) -> object:
    return event.second_limit
'''


@pytest.mark.architecture
class TestSettingsReceiver:
    """The consumer relation is a read ON the settings instance (#1805 verify B2)."""

    def test_only_reads_on_the_settings_instance_count(self) -> None:
        reads = settings_reads(_RECEIVER_FIXTURE, "WorkspaceSettings", frozenset())
        assert "first_limit" in reads
        assert "second_limit" not in reads

    def test_constructed_and_accessor_receivers_count(self) -> None:
        source = (
            "def f():\n"
            "    ws = WorkspaceSettings()\n"
            "    return ws.a, WorkspaceSettings().b, get_settings().workspace.c, other.d\n"
        )
        reads = settings_reads(source, "WorkspaceSettings", frozenset({"workspace"}))
        assert reads == {"a", "b", "c"}

    def test_a_binding_does_not_leak_into_another_function(self) -> None:
        source = (
            "def f(settings: WorkspaceSettings):\n"
            "    return settings.a\n"
            "def g(settings):\n"
            "    return settings.b\n"
        )
        assert settings_reads(source, "WorkspaceSettings", frozenset()) == {"a"}

    def test_root_settings_property_is_discovered(self) -> None:
        from syn_shared.settings.workspace import WorkspaceSettings

        assert "workspace" in _settings_accessors(WorkspaceSettings)
