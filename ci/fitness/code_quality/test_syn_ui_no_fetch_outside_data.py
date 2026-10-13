"""Fitness function: only the data package talks HTTP (ADR-074 rule 1).

ADR-074 rule 1: routes and components never call ``fetch``, never build URLs,
never parse responses. They call a named resource in
``packages/syn-ui/data/src/resources`` through the binding.

Guarded here, over ``apps/syn-ui/src/**``, ``packages/syn-ui/skyline-svelte-v5/src/**``
and ``packages/syn-ui/skyline-core/src/**`` (the Vite proxy config lives outside ``src``):

1. no ``fetch`` at all: no reference to the identifier (``fetch(x)``,
   ``const f = fetch``), no member ``.fetch`` / ``["fetch"]`` / ``[`fetch`]``,
   no ``{ fetch }`` destructuring;
2. no folded string naming ``/api``: a literal, a template's static text, or
   literals joined by ``+`` (``'/ap' + 'i/v1'``), in scripts and in markup
   attributes;
3. outside the binding (``apps/syn-ui/src/lib``), no transport: no import or
   re-export of a binding that resolves, through aliases and re-export chains,
   to the data package's request layer (every value export of
   ``packages/syn-ui/data/src/client/index.ts`` except errors and plain helpers,
   plus ``cached``), no namespace or dynamic import of a module that exports
   one, and no call of anything named ``request`` / ``fetchJSON``.

Facts come from parsing (``_syn_ui``, ``boundary-facts.mjs``). Planted trees
under ``fixtures/syn_ui/transport`` hold every probe from both codex reviews.
Zero tolerance, no exceptions.
"""

from __future__ import annotations

import re

import pytest
from ci.fitness.code_quality._syn_ui import (
    PACKAGE,
    FileFacts,
    Graph,
    Violation,
    expectation,
    is_data,
    parse_violation,
    planted_cases,
    transport,
    tree_base,
)

SCOPE = (
    "apps/syn-ui/src/",
    "packages/syn-ui/skyline-svelte-v5/src/",
    "packages/syn-ui/skyline-core/src/",
)
BINDING = "apps/syn-ui/src/lib/"
API_PATH = re.compile(r"/api(?:/|$|\x00)")
TRANSPORT_NAMES = frozenset({"request", "fetchJSON"})


def _transport_import(graph: Graph, f: FileFacts, base: str) -> list[Violation]:
    wire = transport(graph, base)
    found: list[Violation] = []
    for i in f.imports:
        if i.type_only or i.imported is None or i.resolved is None:
            continue
        if i.imported == "*":
            if graph.exported_symbols(i.resolved) & wire:
                found.append(
                    Violation(
                        f.path, i.line, f"namespace-imports {i.spec}, which exports transport"
                    )
                )
            continue
        sym = graph.resolve_export(i.resolved, i.imported)
        if sym in wire:
            found.append(
                Violation(
                    f.path,
                    i.line,
                    f"imports {i.imported} as {i.local} from {i.spec}: it is transport ({sym.name})",
                )
            )
    for r in f.reexports:
        if r.type_only or r.resolved is None:
            continue
        syms = (
            graph.exported_symbols(r.resolved)
            if r.local == "*"
            else frozenset(s for s in [graph.resolve_export(r.resolved, r.local)] if s)
        )
        if syms & wire:
            found.append(Violation(f.path, r.line, f"re-exports transport from {r.spec}"))
    for d in f.dynamic_imports:
        if d.resolved is not None and graph.exported_symbols(d.resolved) & wire:
            found.append(
                Violation(f.path, d.line, f"dynamically imports {d.spec}, which exports transport")
            )
    for c in f.calls:
        if (
            c.callee
            and c.callee[-1] in TRANSPORT_NAMES
            and (len(c.callee) == 1 or c.callee[0] != "this")
        ):
            found.append(
                Violation(f.path, c.line, f"calls {'.'.join(c.callee)}() (use a named resource)")
            )
    return found


def violations(graph: Graph, base: str) -> list[Violation]:
    found: list[Violation] = []
    for scope in SCOPE:
        for f in graph.under(base, scope):
            found += parse_violation(f)
            found += [
                Violation(f.path, r.line, "references fetch") for r in f.refs if r.name == "fetch"
            ]
            found += [Violation(f.path, line, "reaches a .fetch member") for line in f.member_fetch]
            found += [
                Violation(f.path, s.line, f"names an /api URL ({s.value.replace(chr(0), '${}')!r})")
                for s in f.strings
                if API_PATH.search(s.value)
            ]
            if not f.path.startswith(base + BINDING):
                found += _transport_import(graph, f, base)
    return found


@pytest.mark.architecture
@pytest.mark.host_tool("pnpm")
def test_ui_layers_never_fetch_or_name_the_api(syn_ui_graph: Graph) -> None:
    scanned = [f for s in SCOPE for f in syn_ui_graph.under("", s)]
    assert len(scanned) > 50, f"scanned only {len(scanned)} files; the roots moved?"
    imports_data = [f for f in scanned for i in f.imports if i.resolved and is_data(i.resolved, "")]
    assert len(imports_data) > 10, "found almost no data imports; resolution is broken"
    found = violations(syn_ui_graph, "")
    assert not found, (
        f"ADR-074 rule 1: UI code calls a named resource from {PACKAGE} through the "
        "binding (apps/syn-ui/src/lib/load.svelte.ts), never fetch(), the request layer or an "
        "/api/ URL:\n" + "\n".join(v.render() for v in found)
    )


@pytest.mark.architecture
@pytest.mark.host_tool("pnpm")
def test_transport_is_enumerated_from_the_client_index(syn_ui_graph: Graph) -> None:
    names = {s.name for s in transport(syn_ui_graph, "")}
    assert {"request", "fetchJSON", "seg", "configureClient", "queryCache", "cached"} <= names, (
        names
    )
    assert not names & {"ApiError", "isAbortError", "mapLimit"}, names


@pytest.mark.architecture
@pytest.mark.host_tool("pnpm")
@pytest.mark.parametrize("path", planted_cases("transport"))
def test_planted_transport_probe(path: str, syn_ui_graph: Graph) -> None:
    reported = [v for v in violations(syn_ui_graph, tree_base("transport")) if v.path == path]
    if expectation(path) == "probe":
        assert reported, f"{path}: planted violation was not reported"
    else:
        assert not reported, "\n".join(v.render() for v in reported)
