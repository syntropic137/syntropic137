"""Fitness function: every workspace-hardening setting has a production consumer (#1805).

`SYN_SECURITY_*` documented six workspace limits for over a year and provisioning
read none of them. An operator who set `SYN_SECURITY_MAX_PIDS` got pids 256 from
agentic_isolation's `SecurityConfig.production()`, no error, and a
`.env.example` that still promised the setting worked. #1606 deleted two of its
fields for the same reason and left four behind, because nothing measured the
rest.

So this measures it. For every Settings class in `syn_shared.settings` whose
env prefix is in GOVERNED_PREFIXES, each field must be read by production code:
an attribute access `.<field>` in a non-test module outside `syn_shared/settings`
that names the class. Naming the class is what separates
`settings.memory_limit_mb` from some other object's `memory_limit_mb`.

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
from typing import TYPE_CHECKING

import pytest
from pydantic_settings import BaseSettings

from ci.fitness.conftest import load_exceptions, production_files, rel_path

if TYPE_CHECKING:
    from pathlib import Path

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


@cache
def _consumed_attributes(class_name: str) -> frozenset[str]:
    """Attribute names read in production modules that name `class_name`."""
    attrs: set[str] = set()
    for path in production_files():
        if rel_path(path).startswith(_SETTINGS_DIR):
            continue
        source = path.read_text(encoding="utf-8")
        if class_name not in source:
            continue
        attrs.update(_attribute_reads(path, source))
    return frozenset(attrs)


def _attribute_reads(path: Path, source: str) -> set[str]:
    tree = ast.parse(source, filename=str(path))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    }


def _unconsumed() -> set[str]:
    dead: set[str] = set()
    for cls in _governed_settings():
        consumed = _consumed_attributes(cls.__name__)
        dead.update(
            f"{cls.__name__}.{name}" for name in cls.model_fields if name not in consumed
        )
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
