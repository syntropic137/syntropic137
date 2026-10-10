"""Fitness function: who may import the data package (ADR-074 layering).

ADR-074 layers import only downward: data -> view models -> binding -> routes.
Inside the Skyline UI, ``@syn137/syn-ui-data`` (and its subpaths) is reached
only from

* ``apps/syn-ui/src/routes/**`` (routes),
* ``apps/syn-ui/src/lib/**`` (the binding, including client setup),
* ``apps/syn-ui/src/shell/**`` (the app shell),
* test files (``*.test.ts``, ``*.spec.ts``, ``apps/syn-ui/e2e/**``).

Never from ``skyline-svelte-v5`` or ``skyline-core`` (components and view
models take plain structural types they declare themselves, not even
``import type`` or an ``import('...')`` type, ADR-074), and neither declares it
as a dependency.

What counts as reaching it, with every name resolved through aliases and
re-export chains (``_syn_ui.Graph``): an import, ``export ... from`` or
dynamic ``import()`` / ``require()`` of a module in the data package (however
the specifier is spelled, folded: ``'@syn137/' + 'syn-ui-data'``), an import of
a binding from any module that resolves to a declaration in the data package
(``import { x as y }; export { y }`` in a bridge, at any depth), and a
namespace or dynamic import of a module that re-exports one. A dynamic import
whose argument does not fold to a literal is rejected in the protected
packages, because it cannot be checked. A file that does not parse is a
violation.

Scope is the Skyline UI (``apps/syn-ui`` and ``packages/syn-ui``). Other stacks,
such as the desktop bridge, may use the data package directly: that reuse is
ADR-074 rule 4. Zero tolerance, no exceptions.
"""

from __future__ import annotations

import json

import pytest
from ci.fitness.code_quality._syn_ui import (
    DATA,
    PACKAGE,
    ROOT,
    FileFacts,
    Graph,
    Violation,
    expectation,
    is_data,
    is_test_file,
    parse_violation,
    planted_cases,
    tree_base,
)

ALLOWED = (
    "apps/syn-ui/src/routes/",
    "apps/syn-ui/src/lib/",
    "apps/syn-ui/src/shell/",
    "apps/syn-ui/e2e/",
)
FORBIDDEN_DEPENDENTS = ("skyline-svelte-v5", "skyline-core")
#: Where an unresolvable dynamic import is itself a violation: the layers the rule protects.
PROTECTED = tuple(f"packages/syn-ui/{p}/src/" for p in FORBIDDEN_DEPENDENTS)
SCOPE = ("apps/syn-ui/", "packages/syn-ui/")


def is_allowed(local: str) -> bool:
    return is_test_file(local) or local.startswith(ALLOWED)


def _names_spec(spec: str | None) -> bool:
    return spec is not None and (spec == PACKAGE or spec.startswith(PACKAGE + "/"))


def _module_reaches_data(graph: Graph, module: str | None, base: str) -> bool:
    if module is None:
        return False
    return is_data(module, base) or any(
        is_data(s.module, base) for s in graph.exported_symbols(module)
    )


def reaches(graph: Graph, f: FileFacts, base: str) -> list[Violation]:
    """Each way ``f`` reaches the data package, or cannot be checked."""
    local = f.path[len(base) :]
    found = parse_violation(f)
    for i in f.imports:
        if _names_spec(i.spec) or (i.resolved and is_data(i.resolved, base)):
            found.append(Violation(f.path, i.line, f"imports {i.spec}"))
        elif i.imported == "*" and _module_reaches_data(graph, i.resolved, base):
            found.append(
                Violation(f.path, i.line, f"namespace-imports {i.spec}, which re-exports {PACKAGE}")
            )
        elif i.imported not in (None, "*") and i.resolved is not None:
            sym = graph.resolve_export(i.resolved, i.imported)
            if sym is not None and is_data(sym.module, base):
                found.append(
                    Violation(
                        f.path,
                        i.line,
                        f"imports {i.imported} from {i.spec}, which resolves to {sym.module}",
                    )
                )
    for r in f.reexports:
        if _names_spec(r.spec) or (r.resolved and is_data(r.resolved, base)):
            found.append(Violation(f.path, r.line, f"re-exports {r.spec}"))
        elif r.local == "*" and _module_reaches_data(graph, r.resolved, base):
            found.append(
                Violation(f.path, r.line, f"re-exports {r.spec}, which re-exports {PACKAGE}")
            )
        elif r.local != "*" and r.resolved is not None:
            sym = graph.resolve_export(r.resolved, r.local)
            if sym is not None and is_data(sym.module, base):
                found.append(
                    Violation(
                        f.path, r.line, f"re-exports {r.local}, which resolves to {sym.module}"
                    )
                )
    for d in f.dynamic_imports:
        if d.spec is None:
            if local.startswith(PROTECTED):
                found.append(
                    Violation(f.path, d.line, "dynamic import of a non-literal (cannot be checked)")
                )
        elif _names_spec(d.spec) or _module_reaches_data(graph, d.resolved, base):
            found.append(Violation(f.path, d.line, f"dynamically imports {d.spec}"))
    return found


def violations(graph: Graph, base: str) -> list[Violation]:
    return [
        v
        for scope in SCOPE
        for f in graph.under(base, scope)
        if not f.path[len(base) :].startswith(DATA) and not is_allowed(f.path[len(base) :])
        for v in reaches(graph, f, base)
    ]


@pytest.mark.architecture
@pytest.mark.host_tool("pnpm")
def test_data_package_is_imported_only_by_routes_binding_and_shell(syn_ui_graph: Graph) -> None:
    files = [f for s in SCOPE for f in syn_ui_graph.under("", s) if not f.path.startswith(DATA)]
    direct = [v for f in files for v in reaches(syn_ui_graph, f, "") if PACKAGE in v.what]
    assert len(direct) > 10, f"found only {len(direct)} imports of {PACKAGE}; resolution is broken"
    bad = violations(syn_ui_graph, "")
    assert not bad, (
        f"ADR-074: {PACKAGE} is imported only from apps/syn-ui/src/{{routes,lib,shell}} and tests. "
        "Components and view models take plain data; move the call into the binding or a route:\n"
        + "\n".join(v.render() for v in bad)
    )


@pytest.mark.architecture
@pytest.mark.parametrize("package", FORBIDDEN_DEPENDENTS)
def test_component_and_view_model_packages_do_not_depend_on_data(package: str) -> None:
    manifest = json.loads(
        (ROOT / "packages" / "syn-ui" / package / "package.json").read_text(encoding="utf-8")
    )
    declared = {
        name
        for field in ("dependencies", "devDependencies", "peerDependencies")
        for name in manifest.get(field, {})
    }
    assert PACKAGE not in declared, (
        f"packages/syn-ui/{package} must not depend on {PACKAGE} (ADR-074)"
    )


@pytest.mark.architecture
@pytest.mark.host_tool("pnpm")
@pytest.mark.parametrize("path", planted_cases("imports"))
def test_planted_import_probe(path: str, syn_ui_graph: Graph) -> None:
    reported = [v for v in violations(syn_ui_graph, tree_base("imports")) if v.path == path]
    if expectation(path) == "probe":
        assert reported, f"{path}: planted violation was not reported"
    else:
        assert not reported, "\n".join(v.render() for v in reported)


@pytest.mark.architecture
def test_component_package_is_not_allowed() -> None:
    assert not is_allowed("packages/syn-ui/skyline-svelte-v5/src/components/Button/Button.svelte")
    assert not is_allowed("apps/syn-ui/src/main.ts")
    assert is_allowed("apps/syn-ui/src/routes/executions/List.svelte")
