"""Fitness function: every resource has a fixture route (ADR-074 rule 2).

ADR-074 rule 2: every resource has a fixture under
``packages/syn-ui/data/src/fixtures``, so every screen runs offline
(``VITE_SYN_FIXTURES=1``) and every e2e test runs without an API.

The convention (CONVENTIONS.md, "Fixtures: how to add one"):

* A resource is an exported function in ``packages/syn-ui/data/src/resources/*.ts``
  that sends a request. It calls ``request(path, ...)`` with the path written as
  a string or template literal, directly or through a non-exported helper in
  the same file. Exported functions that send nothing (URL builders such as
  ``executionStreamUrl``) are not resources.
* Each request it sends has a fixture route with the same method and the same
  path shape: ``route('GET', '/executions/:executionId', ...)`` in a
  ``fixtures/*.ts`` file listed in ``fixtures/routes.ts``. A template
  substitution (``${seg(id)}``) and a ``:param`` are the same segment.
* Resources never call ``fetch`` or ``fetchJSON`` themselves, and never pass a
  path the check cannot read.

Zero tolerance, no exceptions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pytest
from ci.fitness.code_quality._syn_ui import DATA, rel, strip_comments

RESOURCES = DATA / "src" / "resources"
FIXTURES = DATA / "src" / "fixtures"

_TOP_FUNCTION = re.compile(r"^(export\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE)
_TOP_LEVEL = re.compile(
    r"^(?:export\s+|async\s+|function\s+|const\s+|let\s+|interface\s+|type\s+)", re.MULTILINE
)
_REQUEST = re.compile(r"(?<![\w$.])request\s*(?:<[^()]*?>)?\s*\(")
_RAW_FETCH = re.compile(r"(?<![\w$])(?:fetch|fetchJSON)\s*\(")
_METHOD = re.compile(r"""\bmethod\s*:\s*['"](GET|POST|PUT|PATCH|DELETE)['"]""")
_FIXTURE_ROUTE = re.compile(
    r"""\broute\(\s*['"](GET|POST|PUT|PATCH|DELETE)['"]\s*,\s*['"]([^'"]+)['"]"""
)
_CALL = re.compile(r"(?<![\w$.])(\w+)\s*\(")


@dataclass(frozen=True)
class Request:
    method: str
    shape: str


@dataclass
class Resource:
    name: str
    path: str
    requests: list[Request] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _close_paren(text: str, open_index: int) -> int:
    """Index of the `)` matching `text[open_index] == '('`, skipping strings and templates."""
    depth = 0
    i = open_index
    while i < len(text):
        c = text[i]
        if c in "'\"`":
            i = _skip_string(text, i)
            continue
        depth += {"(": 1, ")": -1}.get(c, 0)
        if depth == 0:
            return i
        i += 1
    return len(text) - 1


def _skip_string(text: str, start: int) -> int:
    """Index just past the string literal starting at `start` (templates may nest `${}`)."""
    quote = text[start]
    i = start + 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        if quote == "`" and text.startswith("${", i):
            i = _close_brace(text, i + 1) + 1
            continue
        i += 1
    return i


def _close_brace(text: str, open_index: int) -> int:
    depth = 0
    i = open_index
    while i < len(text):
        c = text[i]
        if c in "'\"`":
            i = _skip_string(text, i)
            continue
        depth += {"{": 1, "}": -1}.get(c, 0)
        if depth == 0:
            return i
        i += 1
    return len(text) - 1


def path_shape(literal: str) -> str:
    """'/a/${seg(id)}/b' or '/a/:id/b' -> '/a/:/b'; a query string is not part of the shape."""
    body = literal[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        if body.startswith("${", i):
            i = _close_brace(body, i + 1) + 1
            out.append(":")
            continue
        out.append(body[i])
        i += 1
    path = "".join(out).split("?", 1)[0]
    return "/".join(":" if part.startswith(":") else part for part in path.split("/"))


def _requests_in(code: str) -> tuple[list[Request], list[str]]:
    found: list[Request] = []
    problems: list[str] = []
    for m in _REQUEST.finditer(code):
        open_index = m.end() - 1
        call = code[open_index + 1 : _close_paren(code, open_index)]
        first = call.lstrip()
        if not first or first[0] not in "'\"`":
            problems.append(f"request() path is not a literal: {first[:60]!r}")
            continue
        literal = first[: _skip_string(first, 0)]
        method = _METHOD.search(call[len(literal) :])
        found.append(Request(method.group(1) if method else "GET", path_shape(literal)))
    problems += [
        f"calls {m.group(0).rstrip('(').strip()}() directly" for m in _RAW_FETCH.finditer(code)
    ]
    return found, problems


def _chunks(code: str) -> dict[str, tuple[bool, str]]:
    """Top-level function name -> (exported, its source up to the next top-level declaration)."""
    starts = [m.start() for m in _TOP_LEVEL.finditer(code)] + [len(code)]
    out: dict[str, tuple[bool, str]] = {}
    for m in _TOP_FUNCTION.finditer(code):
        end = next(s for s in starts if s > m.start())
        out[m.group(2)] = (bool(m.group(1)), code[m.start() : end])
    return out


def resources_in(text: str, path: str) -> list[Resource]:
    """Exported functions of one resources file that send requests, with their requests."""
    chunks = _chunks(strip_comments(text))
    out: list[Resource] = []
    for name, (exported, _) in chunks.items():
        if not exported:
            continue
        resource = Resource(name, path)
        seen: set[str] = set()
        todo = [name]
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            body = chunks[current][1]
            requests, problems = _requests_in(body)
            resource.requests += requests
            resource.problems += problems
            todo += [c for c in _CALL.findall(body) if c in chunks and not chunks[c][0]]
        if resource.requests or resource.problems:
            out.append(resource)
    return out


def fixture_routes() -> set[Request]:
    routes: set[Request] = set()
    for f in sorted(FIXTURES.glob("*.ts")):
        code = strip_comments(f.read_text(encoding="utf-8"))
        routes |= {
            Request(m.group(1), path_shape(f"'{m.group(2)}'"))
            for m in _FIXTURE_ROUTE.finditer(code)
        }
    return routes


def registered_fixture_files() -> set[str]:
    code = strip_comments((FIXTURES / "routes.ts").read_text(encoding="utf-8"))
    return {m.group(1) for m in re.finditer(r"""from\s+['"]\./(\w+)['"]""", code)}


@pytest.mark.architecture
def test_every_resource_request_has_a_fixture_route() -> None:
    resources = [
        r
        for f in sorted(RESOURCES.glob("*.ts"))
        for r in resources_in(f.read_text(encoding="utf-8"), rel(f))
    ]
    assert len(resources) > 30, f"found only {len(resources)} resources; the parser is broken"
    routes = fixture_routes()
    missing = [
        f"{r.path}: {r.name} sends {q.method} {q.shape} with no fixture route"
        for r in resources
        for q in r.requests
        if q not in routes
    ]
    problems = [f"{r.path}: {r.name}: {p}" for r in resources for p in r.problems]
    assert not (missing or problems), (
        "ADR-074 rule 2: every resource has a fixture route (see CONVENTIONS.md, Fixtures):\n"
        + "\n".join(missing + problems)
    )


@pytest.mark.architecture
def test_every_fixture_file_with_routes_is_registered() -> None:
    registered = registered_fixture_files()
    unregistered = [
        rel(f)
        for f in sorted(FIXTURES.glob("*.ts"))
        if not f.name.endswith(".test.ts")
        and _FIXTURE_ROUTE.search(strip_comments(f.read_text(encoding="utf-8")))
        and f.stem not in registered | {"define", "router"}
    ]
    assert not unregistered, "fixture routes declared outside fixtures/routes.ts:\n" + "\n".join(
        unregistered
    )


_PLANTED = """
import { request, seg } from '../client'
export function getThing(id: string, signal?: AbortSignal) {
  return cached('getThing', [id], (s) => request(`/things/${seg(id)}`, { signal: s }), { signal })
}
export function makeThing(id: string) {
  return request(`/things/${seg(id)}/make`, { method: 'POST', body: { a: ')' } })
}
export function listThings(signal?: AbortSignal) {
  return load(signal)
}
async function load(signal?: AbortSignal) {
  const r = await request<{ things?: string[] }>('/things', { query: { q: 'x' }, signal })
  return r.things ?? []
}
export function thingStreamUrl(id: string): string {
  return `/sse/things/${seg(id)}`
}
export function sneaky(path: string) {
  return request(path)
}
export function raw() {
  return fetchJSON('/x')
}
"""


@pytest.mark.architecture
def test_parser_reads_planted_resources() -> None:
    found = {r.name: r for r in resources_in(_PLANTED, "planted.ts")}
    assert set(found) == {"getThing", "makeThing", "listThings", "sneaky", "raw"}
    assert found["getThing"].requests == [Request("GET", "/things/:")]
    assert found["makeThing"].requests == [Request("POST", "/things/:/make")]
    assert found["listThings"].requests == [Request("GET", "/things")]
    assert found["sneaky"].problems and found["raw"].problems


@pytest.mark.architecture
def test_fixture_paths_and_templates_share_a_shape() -> None:
    assert path_shape("'/executions/:executionId/cancel'") == path_shape(
        "`/executions/${seg(id)}/cancel`"
    )
    assert path_shape("`/a/${x}/${kind}`") == "/a/:/:"
