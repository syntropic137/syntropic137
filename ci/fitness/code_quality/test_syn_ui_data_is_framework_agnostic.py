"""Fitness function: the data package stays framework-agnostic (ADR-074 rule 4).

ADR-074 rule 4: ``packages/syn-ui/data`` stays plain TypeScript with zero
runtime dependencies, so another UI stack (a React page, a CLI, a Tauri
sidecar) can reuse the same resources and fixtures unchanged. Its query cache
is in-package for the same reason (TanStack Query was rejected, #624).

Guarded here:

* ``packages/syn-ui/data/package.json`` has an empty (or absent)
  ``dependencies``; tooling belongs in ``devDependencies``;
* no source under ``packages/syn-ui/data/src`` imports ``svelte``,
  ``svelte/*`` or ``@sveltejs/*`` (static, ``export from``, or a dynamic
  ``import()`` with a string or template literal);
* nor a UI package (``@syn137/skyline-*``, ``syn-ui``), nor a relative module
  outside ``packages/syn-ui/data`` (a relative path into the app or the
  component packages is a UI import by another name), nor anything through a
  dynamic import whose argument is not a literal.

Zero tolerance, no exceptions.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest
from ci.fitness.code_quality._syn_ui import DATA, module_refs, rel, source_files

if TYPE_CHECKING:
    from pathlib import Path

FRAMEWORK = re.compile(r"^(?:svelte|@sveltejs/[^/]+|@syn137/skyline-[^/]+|syn-ui)(?:/.*)?$")


def framework_imports(text: str, path: Path | None = None) -> list[tuple[int, str]]:
    """(line, spec) for every UI-framework, UI-package, out-of-package or uncheckable import."""
    out: list[tuple[int, str]] = []
    for ref in module_refs(text):
        if ref.spec is None:
            out.append((ref.line, "import(<non-literal>)"))
        elif FRAMEWORK.match(ref.spec):
            out.append((ref.line, ref.spec))
        elif ref.spec.startswith(".") and path is not None:
            if ref.spec.endswith("?raw") and path.name.endswith(".test.ts"):
                continue  # a test reading another repo file as text (the API source it pins)
            target = (path.parent / ref.spec).resolve()
            if not target.is_relative_to(DATA):
                out.append((ref.line, f"{ref.spec} (outside packages/syn-ui/data)"))
    return out


@pytest.mark.architecture
def test_data_package_has_no_runtime_dependencies() -> None:
    manifest = json.loads((DATA / "package.json").read_text(encoding="utf-8"))
    deps = manifest.get("dependencies", {})
    peers = manifest.get("peerDependencies", {})
    assert not deps, (
        f"ADR-074: @syn137/syn-ui-data has zero runtime dependencies, found {sorted(deps)}"
    )
    assert not peers, (
        f"ADR-074: @syn137/syn-ui-data has zero runtime dependencies, found peers {sorted(peers)}"
    )


@pytest.mark.architecture
def test_data_sources_import_no_svelte() -> None:
    files = source_files(DATA / "src")
    assert len(files) > 20, f"scanned only {len(files)} files under packages/syn-ui/data/src"
    found = [
        f"{rel(f)}:{line}: imports {spec}"
        for f in files
        for line, spec in framework_imports(f.read_text(encoding="utf-8"), f)
    ]
    assert not found, (
        "ADR-074: the data package imports no UI framework, UI package or module outside itself:\n"
        + "\n".join(found)
    )


@pytest.mark.architecture
@pytest.mark.parametrize(
    "text",
    [
        "import { untrack } from 'svelte'",
        "import { writable } from 'svelte/store'",
        'import x from "@sveltejs/vite-plugin-svelte"',
        "const s = await import('svelte')",
        "const s = await import(`svelte`)",
        "const s = await import(`svelte/store`)",
        "export { untrack } from 'svelte'",
        "const s = await import(name)",
        "import { Button } from '@syn137/skyline-svelte-v5'",
        "const s = ' /* '; import('svelte'); const e = ' */ '",
    ],
)
def test_planted_framework_import_is_caught(text: str) -> None:
    assert framework_imports(text), text


@pytest.mark.architecture
@pytest.mark.parametrize(
    "spec",
    ["../../../../apps/syn-ui/src/lib/load.svelte", "../../../skyline-core/src/format"],
)
def test_planted_relative_ui_import_is_caught(spec: str) -> None:
    importer = DATA / "src" / "resources" / "planted.ts"
    assert framework_imports(f"import {{ x }} from '{spec}'", importer), spec
    assert not framework_imports("import { request } from '../client'", importer)
    assert framework_imports("import src from '../../../x.py?raw'", importer)  # not a test file


@pytest.mark.architecture
def test_lookalikes_pass() -> None:
    assert not framework_imports(
        "import x from 'svelte-check-free'\n// import 'svelte'\nconst a = 'svelte'"
    )
