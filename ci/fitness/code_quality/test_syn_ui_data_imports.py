"""Fitness function: who may import the data package (ADR-074 layering).

ADR-074 layers import only downward: data -> view models -> binding -> routes.
Inside the Skyline UI, ``@syn137/syn-ui-data`` (and its subpaths) is imported
only from

* ``apps/syn-ui/src/routes/**`` (routes),
* ``apps/syn-ui/src/lib/**`` (the binding, including client setup),
* ``apps/syn-ui/src/shell/**`` (the app shell),
* test files (``*.test.ts``, ``*.spec.ts``, ``apps/syn-ui/e2e/**``).

Never from ``skyline-svelte-v5`` or ``skyline-core`` (components and view
models take plain data), and neither declares it as a dependency.

Scope is the Skyline UI (``apps/syn-ui`` and ``packages/syn-ui``). Other stacks,
such as the desktop bridge, may use the data package directly: that reuse is
ADR-074 rule 4. Zero tolerance, no exceptions.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest
from ci.fitness.code_quality._syn_ui import (
    DATA,
    SYN_UI_APP,
    SYN_UI_PACKAGES,
    line_of,
    rel,
    source_files,
    strip_comments,
)

if TYPE_CHECKING:
    from pathlib import Path

PACKAGE = "@syn137/syn-ui-data"
ALLOWED_DIRS = (
    *tuple(SYN_UI_APP / "src" / d for d in ("routes", "lib", "shell")),
    SYN_UI_APP / "e2e",
)
FORBIDDEN_DEPENDENTS = ("skyline-svelte-v5", "skyline-core")

#: `from '@syn137/syn-ui-data...'`, `import '...'`, `import('...')`, `require('...')`.
IMPORT = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['"](@syn137/syn-ui-data(?:/[^'"]*)?)['"]"""
)


def is_test_file(path: Path) -> bool:
    return path.name.endswith((".test.ts", ".spec.ts", ".test.js", ".spec.js"))


def is_allowed(path: Path) -> bool:
    return is_test_file(path) or any(path.is_relative_to(d) for d in ALLOWED_DIRS)


def imports_in(text: str) -> list[tuple[int, str]]:
    code = strip_comments(text)
    return [(line_of(code, m.start()), m.group(1)) for m in IMPORT.finditer(code)]


def _scanned_files() -> list[Path]:
    files = source_files(SYN_UI_APP) + source_files(SYN_UI_PACKAGES)
    return [f for f in files if not f.is_relative_to(DATA)]


@pytest.mark.architecture
def test_data_package_is_imported_only_by_routes_binding_and_shell() -> None:
    files = _scanned_files()
    importers = [
        (f, line, spec) for f in files for line, spec in imports_in(f.read_text(encoding="utf-8"))
    ]
    assert len(importers) > 10, (
        f"found only {len(importers)} imports of {PACKAGE}; the scan is broken"
    )
    bad = [f"{rel(f)}:{line}: imports {spec}" for f, line, spec in importers if not is_allowed(f)]
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
    "export { getExecution } from '@syn137/syn-ui-data'",
]


@pytest.mark.architecture
@pytest.mark.parametrize("text", PLANTED)
def test_planted_import_is_seen(text: str) -> None:
    assert imports_in(text), text


@pytest.mark.architecture
def test_comment_mentions_are_not_imports() -> None:
    assert not imports_in(
        "// import { x } from '@syn137/syn-ui-data'\n/** serves @syn137/syn-ui-data fixtures */"
    )


@pytest.mark.architecture
def test_component_package_is_not_allowed() -> None:
    planted = (
        SYN_UI_PACKAGES / "skyline-svelte-v5" / "src" / "components" / "Button" / "Button.svelte"
    )
    assert not is_allowed(planted)
    assert not is_allowed(SYN_UI_APP / "src" / "main.ts")
    assert is_allowed(SYN_UI_APP / "src" / "routes" / "executions" / "List.svelte")
