"""Fitness function: the data package stays framework-agnostic (ADR-074 rule 4).

ADR-074 rule 4: ``packages/syn-ui/data`` stays plain TypeScript with zero
runtime dependencies, so another UI stack (a React page, a CLI, a Tauri
sidecar) can reuse the same resources and fixtures unchanged. Its query cache
is in-package for the same reason (TanStack Query was rejected, #624).

Guarded here:

* ``packages/syn-ui/data/package.json`` has an empty (or absent)
  ``dependencies`` and ``peerDependencies``; tooling belongs in ``devDependencies``;
* no source under ``packages/syn-ui/data/src`` imports, re-exports or
  dynamically imports (specifiers folded, so ``import(`svelte`)`` and
  ``'sve' + 'lte'`` count) ``svelte``, ``svelte/*``, ``@sveltejs/*``, a UI
  package (``@syn137/skyline-*``, ``syn-ui``) or any other workspace package;
* nor a relative module outside ``packages/syn-ui/data`` (a relative path into
  the app or the component packages is a UI import by another name). The only
  ways out: a type-only import of generated types (a ``generated/`` directory),
  and a test reading another repo file as text (``?raw``);
* nor anything through a dynamic import whose argument does not fold to a
  literal; and every file parses.

Facts come from parsing (``_syn_ui``). Zero tolerance, no exceptions.
"""

from __future__ import annotations

import json
import re

import pytest
from ci.fitness.code_quality._syn_ui import (
    DATA,
    PACKAGE,
    ROOT,
    FileFacts,
    Graph,
    Violation,
    expectation,
    is_test_file,
    parse_violation,
    planted_cases,
    relative_target,
    tree_base,
)

FRAMEWORK = re.compile(r"^(?:svelte|@sveltejs/[^/]+|@syn137/skyline-[^/]+|syn-ui)(?:/.*)?$")


def _check_spec(
    f: FileFacts, base: str, line: int, spec: str | None, resolved: str | None, type_only: bool
) -> list[Violation]:
    data_dir = base + DATA
    if spec is None:
        return [Violation(f.path, line, "import(<non-literal>) cannot be checked")]
    if FRAMEWORK.match(spec):
        return [Violation(f.path, line, f"imports {spec}")]
    if spec.startswith("."):
        target = relative_target(f.path, spec)
        if (target + "/").startswith(data_dir):
            return []
        if spec.endswith("?raw") and is_test_file(f.path):
            return []  # a test reading another repo file as text (the API source it pins)
        if type_only and "/generated/" in f"/{target}":
            return []
        return [Violation(f.path, line, f"imports {spec} (outside packages/syn-ui/data)")]
    if resolved is not None and not resolved.startswith(DATA) and not resolved.startswith(data_dir):
        return [Violation(f.path, line, f"imports workspace package {spec} ({resolved})")]
    return []


def violations(graph: Graph, base: str) -> list[Violation]:
    found: list[Violation] = []
    for f in graph.under(base, DATA + "src/"):
        found += parse_violation(f)
        for i in f.imports:
            found += _check_spec(f, base, i.line, i.spec, i.resolved, i.type_only)
        for r in f.reexports:
            found += _check_spec(f, base, r.line, r.spec, r.resolved, r.type_only)
        for d in f.dynamic_imports:
            found += _check_spec(f, base, d.line, d.spec, d.resolved, False)
    return found


@pytest.mark.architecture
def test_data_package_has_no_runtime_dependencies() -> None:
    manifest = json.loads((ROOT / DATA / "package.json").read_text(encoding="utf-8"))
    deps = manifest.get("dependencies", {})
    peers = manifest.get("peerDependencies", {})
    assert not deps, f"ADR-074: {PACKAGE} has zero runtime dependencies, found {sorted(deps)}"
    assert not peers, (
        f"ADR-074: {PACKAGE} has zero runtime dependencies, found peers {sorted(peers)}"
    )


@pytest.mark.architecture
@pytest.mark.host_tool("pnpm")
def test_data_sources_import_no_ui(syn_ui_graph: Graph) -> None:
    files = syn_ui_graph.under("", DATA + "src/")
    assert len(files) > 20, f"parsed only {len(files)} files under packages/syn-ui/data/src"
    found = violations(syn_ui_graph, "")
    assert not found, (
        "ADR-074: the data package imports no UI framework, UI package or module outside itself:\n"
        + "\n".join(v.render() for v in found)
    )


@pytest.mark.architecture
@pytest.mark.host_tool("pnpm")
@pytest.mark.parametrize("path", planted_cases("data"))
def test_planted_data_probe(path: str, syn_ui_graph: Graph) -> None:
    reported = [v for v in violations(syn_ui_graph, tree_base("data")) if v.path == path]
    if expectation(path) == "probe":
        assert reported, f"{path}: planted violation was not reported"
    else:
        assert not reported, "\n".join(v.render() for v in reported)
