"""Fitness function: who may import the data package (ADR-074 layering).

ADR-074 layers import only downward: data -> view models -> binding -> routes.
Inside the Skyline UI, ``@syn137/syn-ui-data`` (and its subpaths) is imported
only from

* ``apps/syn-ui/src/routes/**`` (routes),
* ``apps/syn-ui/src/lib/**`` (the binding, including client setup),
* ``apps/syn-ui/src/shell/**`` (the app shell),
* test files (``*.test.ts``, ``*.spec.ts``, ``apps/syn-ui/e2e/**``).

Never from ``skyline-svelte-v5`` or ``skyline-core`` (components and view
models take plain structural types they declare themselves, not even
``import type`` from the data package, ADR-074), and neither declares it as a
dependency.

What counts as importing it: a static import or ``export ... from``, a
dynamic ``import()`` or ``require()`` whose argument is a string or template
literal, and importing a relative module that re-exports the data package
(one level: ``export * from``, ``export { x } from``, or ``import { x }`` then
``export { x }``). Outside the allowed directories a dynamic import whose
argument is not a literal is rejected too, because it cannot be checked.

Scope is the Skyline UI (``apps/syn-ui`` and ``packages/syn-ui``). Other stacks,
such as the desktop bridge, may use the data package directly: that reuse is
ADR-074 rule 4. Zero tolerance, no exceptions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from ci.fitness.code_quality._syn_ui import (
    DATA,
    SYN_UI_APP,
    SYN_UI_PACKAGES,
    is_svelte,
    local_exports,
    module_refs,
    rel,
    resolve_relative,
    source_files,
)

if TYPE_CHECKING:
    from pathlib import Path

PACKAGE = "@syn137/syn-ui-data"
ALLOWED_DIRS = (
    *tuple(SYN_UI_APP / "src" / d for d in ("routes", "lib", "shell")),
    SYN_UI_APP / "e2e",
)
FORBIDDEN_DEPENDENTS = ("skyline-svelte-v5", "skyline-core")
#: Where an unresolvable dynamic import is itself a violation: the layers the rule protects.
PROTECTED = tuple(SYN_UI_PACKAGES / p / "src" for p in FORBIDDEN_DEPENDENTS)
UNCHECKABLE = "dynamic import of a non-literal (cannot be checked)"


def is_test_file(path: Path) -> bool:
    return path.name.endswith((".test.ts", ".spec.ts", ".test.js", ".spec.js"))


def is_allowed(path: Path) -> bool:
    return is_test_file(path) or any(path.is_relative_to(d) for d in ALLOWED_DIRS)


def _is_package(spec: str | None) -> bool:
    return spec is not None and (spec == PACKAGE or spec.startswith(PACKAGE + "/"))


def reexports_package(text: str, *, svelte: bool = False) -> bool:
    """Does this module hand the data package on (`export * from`, `export {x} from`, import+export)?"""
    refs = module_refs(text, svelte=svelte)
    if any(r.reexport and _is_package(r.spec) for r in refs):
        return True
    imported = {n for r in refs if not r.reexport and _is_package(r.spec) for n in r.names}
    namespaces = bool([r for r in refs if r.namespace and _is_package(r.spec)])
    exported = local_exports(text, svelte=svelte)
    return bool(imported & exported) or (namespaces and bool(exported))


def _bridges(importer: Path | None, spec: str) -> bool:
    """Is `spec`, relative to `importer`, a module that re-exports the data package?"""
    target = resolve_relative(importer, spec) if importer is not None else None
    return target is not None and reexports_package(
        target.read_text(encoding="utf-8"), svelte=is_svelte(target)
    )


def imports_in(text: str, path: Path | None = None) -> list[tuple[int, str]]:
    """(line, what) for each way this file reaches the data package, or cannot be checked."""
    svelte = path is not None and is_svelte(path)
    out: list[tuple[int, str]] = []
    for ref in module_refs(text, svelte=svelte):
        if _is_package(ref.spec):
            out.append((ref.line, f"imports {ref.spec}"))
        elif ref.spec is None:
            out.append((ref.line, UNCHECKABLE))
        elif _bridges(path, ref.spec):
            out.append((ref.line, f"imports {ref.spec}, which re-exports {PACKAGE}"))
    return out


def _scanned_files() -> list[Path]:
    files = source_files(SYN_UI_APP) + source_files(SYN_UI_PACKAGES)
    return [f for f in files if not f.is_relative_to(DATA)]


@pytest.mark.architecture
def test_data_package_is_imported_only_by_routes_binding_and_shell() -> None:
    files = _scanned_files()
    importers = [
        (f, line, what)
        for f in files
        for line, what in imports_in(f.read_text(encoding="utf-8"), f)
    ]
    direct = [i for i in importers if PACKAGE in i[2]]
    assert len(direct) > 10, f"found only {len(direct)} imports of {PACKAGE}; the scan is broken"
    bad = [
        f"{rel(f)}:{line}: {what}"
        for f, line, what in importers
        if not is_allowed(f)
        and (what != UNCHECKABLE or any(f.is_relative_to(d) for d in PROTECTED))
    ]
    assert not bad, (
        f"ADR-074: {PACKAGE} is imported only from apps/syn-ui/src/{{routes,lib,shell}} and tests. "
        "Components and view models take plain data; move the call into the binding or a route:\n"
        + "\n".join(bad)
    )


@pytest.mark.architecture
@pytest.mark.parametrize("package", FORBIDDEN_DEPENDENTS)
def test_component_and_view_model_packages_do_not_depend_on_data(package: str) -> None:
    manifest = json.loads((SYN_UI_PACKAGES / package / "package.json").read_text(encoding="utf-8"))
    declared = {
        name
        for field in ("dependencies", "devDependencies", "peerDependencies")
        for name in manifest.get(field, {})
    }
    assert PACKAGE not in declared, (
        f"packages/syn-ui/{package} must not depend on {PACKAGE} (ADR-074)"
    )


PLANTED = [
    "import { listExecutions } from '@syn137/syn-ui-data'",
    'import type { X } from "@syn137/syn-ui-data/types"',
    "const live = await import('@syn137/syn-ui-data/live')",
    "const live = await import(`@syn137/syn-ui-data`)",
    "const live = await import(name)",
    "const live = await import('@syn137/' + 'syn-ui-data')",
    "export { getExecution } from '@syn137/syn-ui-data'",
    "export * from '@syn137/syn-ui-data'",
    "<script>const s = ' /* '; import('@syn137/syn-ui-data'); const e = ' */ '</script>",
]


@pytest.mark.architecture
@pytest.mark.parametrize("text", PLANTED)
def test_planted_import_is_seen(text: str) -> None:
    path = SYN_UI_PACKAGES / "skyline-core" / "src" / ("x.svelte" if "<script" in text else "x.ts")
    assert imports_in(text, path), text


@pytest.mark.architecture
def test_comment_and_string_mentions_are_not_imports() -> None:
    assert not imports_in(
        "// import { x } from '@syn137/syn-ui-data'\n/** serves @syn137/syn-ui-data fixtures */\n"
        "const s = \"import('@syn137/syn-ui-data')\""
    )


@pytest.mark.architecture
@pytest.mark.parametrize(
    "bridge",
    [
        "export * from '@syn137/syn-ui-data'",
        "export { listExecutions } from '@syn137/syn-ui-data'",
        "import { listExecutions } from '@syn137/syn-ui-data'\nexport { listExecutions }",
        "import * as data from '@syn137/syn-ui-data'\nconst d = data\nexport { d }",
    ],
)
def test_relative_bridge_that_reexports_data_counts(bridge: str, tmp_path: Path) -> None:
    (tmp_path / "bridge.ts").write_text(bridge, encoding="utf-8")
    component = tmp_path / "Thing.svelte"
    text = "<script lang=\"ts\">import { listExecutions } from './bridge'</script>"
    assert imports_in(text, component), bridge


@pytest.mark.architecture
def test_relative_module_that_only_uses_data_is_not_a_bridge(tmp_path: Path) -> None:
    (tmp_path / "load.svelte.ts").write_text(
        "import { queryCache } from '@syn137/syn-ui-data'\nexport function resource() { return queryCache }",
        encoding="utf-8",
    )
    assert not imports_in("import { resource } from './load.svelte'", tmp_path / "Thing.ts")


@pytest.mark.architecture
def test_component_package_is_not_allowed() -> None:
    planted = (
        SYN_UI_PACKAGES / "skyline-svelte-v5" / "src" / "components" / "Button" / "Button.svelte"
    )
    assert not is_allowed(planted)
    assert not is_allowed(SYN_UI_APP / "src" / "main.ts")
    assert is_allowed(SYN_UI_APP / "src" / "routes" / "executions" / "List.svelte")
