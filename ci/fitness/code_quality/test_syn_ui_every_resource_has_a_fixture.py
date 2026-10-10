"""Fitness function: every resource has a fixture route (ADR-074 rule 2).

ADR-074 rule 2: every resource has a fixture under
``packages/syn-ui/data/src/fixtures``, so every screen runs offline
(``VITE_SYN_FIXTURES=1``) and every e2e test runs without an API.

The convention (CONVENTIONS.md, "Fixtures: how to add one"), checked on parsed
facts (``_syn_ui``), never on text:

* A resource is an exported value binding of ``packages/syn-ui/data/src/resources/*.ts``
  (``export function``, an exported arrow or const, a local exported by an
  ``export { x as y }`` list, at any indentation) whose body, or a top-level
  helper it references, calls the data package's ``request`` (resolved
  through aliases and namespace imports, so ``send`` or ``client.request`` is
  ``request`` when it resolves there). Exported functions that send nothing
  (URL builders such as ``executionStreamUrl``) are not resources.
* The path is ``request``'s whole first argument, folded: a string, a template
  (each ``${}`` is one segment) or literals joined by ``+``. Anything else is
  a problem, as is a ``method`` that is not a literal and any direct
  ``fetch`` / ``fetchJSON`` call.
* Each request has a fixture route with the same method and path shape: a
  ``route(METHOD, PATH, ...)`` CALL EXPRESSION (resolved to
  ``fixtures/define.ts``'s ``route``; a string that looks like one counts for
  nothing) inside a declaration reachable from the ``routes`` that
  ``fixtures/router.ts`` compiles: ``routes`` in ``routes.ts``, the arrays it
  spreads, and what those reference. A route in a test file, in an array
  nothing references, or in a module routes.ts imports without using serves
  nothing and does not count. Every fixture module with routes must be reached.

Planted trees under ``fixtures/syn_ui/resources`` hold every probe from both
codex reviews. Zero tolerance, no exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from ci.fitness.code_quality._syn_ui import (
    Call,
    FileFacts,
    Graph,
    Symbol,
    Violation,
    client_index,
    expectation,
    is_test_file,
    parse_violation,
    planted_cases,
    tree_base,
)

RESOURCES = "packages/syn-ui/data/src/resources/"
FIXTURES = "packages/syn-ui/data/src/fixtures/"


@dataclass(frozen=True)
class Request:
    method: str
    shape: str


@dataclass
class Resource:
    name: str
    path: str
    line: int
    requests: list[Request] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def path_shape(value: str) -> str:
    """'/a/\\x00/b' (a folded template) or '/a/:id/b' -> '/a/:/b'; the query string is not part of it."""
    path = value.split("?", 1)[0]
    return "/".join(
        ":" if "\x00" in part or part.startswith(":") else part for part in path.split("/")
    )


def _reach(f: FileFacts, start: str) -> set[str]:
    """Top-level declarations ``start`` uses, transitively (first names)."""
    decls = {n: d for d in f.decls for n in d.names}
    seen: set[str] = set()
    todo = [start]
    while todo:
        name = todo.pop()
        d = decls.get(name)
        if d is None or d.names[0] in seen:
            continue
        seen.add(d.names[0])
        todo += list(d.refs)
    return seen


def _request(graph: Graph, base: str) -> tuple[Symbol | None, frozenset[Symbol]]:
    index = client_index(graph, base)
    raw = {Symbol("<global>", "fetch")}
    if (fetch_json := graph.resolve_export(index, "fetchJSON")) is not None:
        raw.add(fetch_json)
    return graph.resolve_export(index, "request"), frozenset(raw)


def _read(c: Call, resource: Resource) -> None:
    path = c.args[0] if c.args else None
    if path is None or path.kind == "dynamic":
        resource.problems.append(
            f"request() path is not a literal: {path.value if path else '<none>'!r}"
        )
        return
    if not c.method_known:
        resource.problems.append(f"request({path.value!r}) method is not a literal")
        return
    resource.requests.append(Request(c.method or "GET", path_shape(path.value)))


def resources_in(graph: Graph, f: FileFacts, base: str) -> list[Resource]:
    """Exported bindings of one resources file that send requests, with their requests."""
    request, raw = _request(graph, base)
    decls = {n: d for d in f.decls for n in d.names}
    out: list[Resource] = []
    for e in f.exports:
        if e.type_only or e.local is None or e.local not in decls:
            continue
        resource = Resource(e.exported, f.path, e.line)
        reach = _reach(f, e.local)
        for c in f.calls:
            if c.decl not in reach:
                continue
            sym = graph.resolve_callee(f, c.callee)
            if sym is not None and sym == request:
                _read(c, resource)
            elif (sym is not None and sym in raw) or (
                c.callee and c.callee[-1] in ("fetch", "fetchJSON")
            ):
                resource.problems.append(f"calls {'.'.join(c.callee or ())}() directly")
        if resource.requests or resource.problems:
            out.append(resource)
    return out


@dataclass
class Served:
    routes: set[Request] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    problems: list[Violation] = field(default_factory=list)


def fixture_routes(graph: Graph, base: str) -> Served:
    """Routes the fixtures router serves: route() calls reachable from what router.ts compiles."""
    router = graph.files[base + FIXTURES + "router.ts"]
    route = graph.resolve_export(base + FIXTURES + "define.ts", "route")
    starts = [
        c.args[0].value
        for c in router.calls
        if c.callee == ("compile",)
        and c.args
        and c.args[0].kind == "dynamic"
        and c.args[0].value.isidentifier()
    ]
    assert starts, f"{router.path}: no compile(<name>) call; the router changed shape"
    served = Served()
    todo = [graph.resolve_local(router.path, name) for name in starts]
    seen: set[Symbol] = set()
    while todo:
        sym = todo.pop()
        if sym is None or sym in seen or sym.module not in graph.files:
            continue
        seen.add(sym)
        f = graph.files[sym.module]
        decl = next((d for d in f.decls if sym.name in d.names), None)
        if decl is None:
            continue
        for c in f.calls:
            if c.decl != decl.names[0] or graph.resolve_callee(f, c.callee) != route:
                continue
            served.files.add(f.path)
            method, path = (*c.args, None, None)[:2]
            if method is None or path is None or method.kind != "literal" or path.kind != "literal":
                served.problems.append(
                    Violation(f.path, c.line, "route() method and path must be literals")
                )
                continue
            served.routes.add(Request(method.value, path_shape(path.value)))
        todo += [graph.resolve_local(f.path, ref) for ref in decl.refs]
    return served


def _defines_routes(graph: Graph, f: FileFacts, route: Symbol | None) -> bool:
    return any(graph.resolve_callee(f, c.callee) == route for c in f.calls)


def violations(graph: Graph, base: str) -> list[Violation]:
    found: list[Violation] = []
    served = fixture_routes(graph, base)
    found += served.problems
    for f in graph.under(base, RESOURCES):
        if is_test_file(f.path):
            continue
        found += parse_violation(f)
        for r in resources_in(graph, f, base):
            found += [Violation(r.path, r.line, f"{r.name}: {p}") for p in r.problems]
            found += [
                Violation(
                    r.path, r.line, f"{r.name} sends {q.method} {q.shape} with no fixture route"
                )
                for q in r.requests
                if q not in served.routes
            ]
    route = graph.resolve_export(base + FIXTURES + "define.ts", "route")
    for f in graph.under(base, FIXTURES):
        found += parse_violation(f)
        if (
            not is_test_file(f.path)
            and f.path not in served.files
            and _defines_routes(graph, f, route)
        ):
            found.append(
                Violation(
                    f.path, 1, "declares fixture routes that fixtures/routes.ts never composes"
                )
            )
    return found


@pytest.mark.architecture
@pytest.mark.host_tool("pnpm")
def test_every_resource_request_has_a_fixture_route(syn_ui_graph: Graph) -> None:
    resources = [
        r for f in syn_ui_graph.under("", RESOURCES) for r in resources_in(syn_ui_graph, f, "")
    ]
    assert len(resources) > 30, f"found only {len(resources)} resources; the parser is broken"
    served = fixture_routes(syn_ui_graph, "")
    assert len(served.files) >= 8 and len(served.routes) > 30, served.files
    found = violations(syn_ui_graph, "")
    assert not found, (
        "ADR-074 rule 2: every resource has a fixture route (see CONVENTIONS.md, Fixtures):\n"
        + "\n".join(v.render() for v in found)
    )


@pytest.mark.architecture
@pytest.mark.host_tool("pnpm")
@pytest.mark.parametrize("path", planted_cases("resources"))
def test_planted_resource_probe(path: str, syn_ui_graph: Graph) -> None:
    reported = [v for v in violations(syn_ui_graph, tree_base("resources")) if v.path == path]
    if expectation(path) == "probe":
        assert reported, f"{path}: planted violation was not reported"
    else:
        assert not reported, "\n".join(v.render() for v in reported)


@pytest.mark.architecture
def test_fixture_paths_and_templates_share_a_shape() -> None:
    assert path_shape("/executions/:executionId/cancel") == path_shape("/executions/\x00/cancel")
    assert path_shape("/a/\x00/\x00?x=1") == "/a/:/:"
