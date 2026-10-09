"""Fitness function: the data package stays framework-agnostic (ADR-074 rule 4).

ADR-074 rule 4: ``packages/syn-ui/data`` stays plain TypeScript with zero
runtime dependencies, so another UI stack (a React page, a CLI, a Tauri
sidecar) can reuse the same resources and fixtures unchanged. Its query cache
is in-package for the same reason (TanStack Query was rejected, #624).

Guarded here:

* ``packages/syn-ui/data/package.json`` has an empty (or absent)
  ``dependencies``; tooling belongs in ``devDependencies``;
* no source under ``packages/syn-ui/data/src`` imports ``svelte``,
  ``svelte/*`` or ``@sveltejs/*``.

Zero tolerance, no exceptions.
"""

from __future__ import annotations

import json
import re

import pytest
from ci.fitness.code_quality._syn_ui import DATA, line_of, rel, source_files, strip_comments

FRAMEWORK_IMPORT = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['"]((?:svelte|@sveltejs/[^'"/]+)(?:/[^'"]*)?)['"]"""
)


def framework_imports(text: str) -> list[tuple[int, str]]:
    code = strip_comments(text)
    return [(line_of(code, m.start()), m.group(1)) for m in FRAMEWORK_IMPORT.finditer(code)]


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
        for line, spec in framework_imports(f.read_text(encoding="utf-8"))
    ]
    assert not found, "ADR-074: the data package never imports Svelte:\n" + "\n".join(found)


@pytest.mark.architecture
@pytest.mark.parametrize(
    "text",
    [
        "import { untrack } from 'svelte'",
        "import { writable } from 'svelte/store'",
        'import x from "@sveltejs/vite-plugin-svelte"',
        "const s = await import('svelte')",
    ],
)
def test_planted_framework_import_is_caught(text: str) -> None:
    assert framework_imports(text), text


@pytest.mark.architecture
def test_lookalikes_pass() -> None:
    assert not framework_imports(
        "import x from 'svelte-check-free'\n// import 'svelte'\nconst a = 'svelte'"
    )
